//! Compiled kernels of the ETF AI Cockpit. Each kernel is the one production path of its calculation;
//! the former numpy/pandas form lives only in the tests as the oracle (bit-exact parity).
//! Per-instrument kernels take a frame sorted by (id, date) and group offsets: group g is the
//! contiguous row range [offsets[g], offsets[g + 1]).
use numpy::ndarray::Array2;
use numpy::{IntoPyArray, PyArray1, PyArray2, PyReadonlyArray1, PyReadonlyArray2};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rayon::prelude::*;

mod as_traded;
mod momentum;
mod pit;
mod returns;

fn groups(n: usize, offsets: &[i64]) -> PyResult<Vec<(usize, usize)>> {
    if offsets.first() != Some(&0) || offsets.last().map(|&e| e as usize) != Some(n) || offsets.windows(2).any(|w| w[0] > w[1]) {
        return Err(PyValueError::new_err("offsets must rise from 0 to the row count"));
    }
    Ok(offsets.windows(2).map(|w| (w[0] as usize, w[1] as usize)).collect())
}

/// Worst `price / running window peak - 1` in each trailing window (numpy sliding-window form):
/// NaN until the window is full, and NaN when any price or ratio in the window is NaN.
fn max_drawdown(x: &[f64], w: usize, out: &mut [f64]) {
    for i in 0..x.len() {
        out[i] = f64::NAN;
        if i + 1 < w {
            continue;
        }
        let (mut peak, mut worst) = (f64::NEG_INFINITY, f64::INFINITY);
        for &v in &x[i + 1 - w..=i] {
            if v > peak {
                peak = v;
            }
            let d = v / peak - 1.0;
            // a NaN price (or ratio, e.g. 0/0) makes the numpy window NaN: np.maximum and np.min propagate it
            if d.is_nan() {
                worst = f64::NAN;
                break;
            }
            if d < worst {
                worst = d;
            }
        }
        out[i] = worst;
    }
}

/// pandas 2.3 `rolling(window, min_periods=window).mean()` (aggregations.pyx `roll_mean`: Kahan add/remove).
fn rolling_mean_pd(v: &[f64], w: usize, out: &mut [f64]) {
    let (mut nobs, mut sum, mut neg, mut comp_add, mut comp_rem, mut same, mut prev) = (0i64, 0.0f64, 0i64, 0.0f64, 0.0f64, 0i64, 0.0f64);
    for i in 0..v.len() {
        let (s, e) = ((i + 1).saturating_sub(w), i + 1);
        let from = if i == 0 || s >= i {
            (nobs, sum, neg, comp_add, comp_rem, same, prev) = (0, 0.0, 0, 0.0, 0.0, 0, v[s]);
            s
        } else {
            for &x in &v[i.saturating_sub(w)..s] {
                if x == x {
                    nobs -= 1;
                    let y = -x - comp_rem;
                    let t = sum + y;
                    comp_rem = t - sum - y;
                    sum = t;
                    if x.is_sign_negative() {
                        neg -= 1;
                    }
                }
            }
            i
        };
        for &x in &v[from..e] {
            if x == x {
                nobs += 1;
                let y = x - comp_add;
                let t = sum + y;
                comp_add = t - sum - y;
                sum = t;
                if x.is_sign_negative() {
                    neg += 1;
                }
                same = if x == prev { same + 1 } else { 1 };
                prev = x;
            }
        }
        out[i] = if nobs >= w as i64 && nobs > 0 {
            let r = sum / nobs as f64;
            if same >= nobs {
                prev
            } else if (neg == 0 && r < 0.0) || (neg == nobs && r > 0.0) {
                0.0
            } else {
                r
            }
        } else {
            f64::NAN
        };
    }
}

/// pandas 2.3 `rolling(window, min_periods=window).std()` (ddof 1; `roll_var`: Welford with Kahan, then zsqrt).
fn rolling_std_pd(v: &[f64], w: usize, out: &mut [f64]) {
    let (mut nobs, mut mean, mut ssq, mut comp_add, mut comp_rem, mut same, mut prev) = (0i64, 0.0f64, 0.0f64, 0.0f64, 0.0f64, 0i64, 0.0f64);
    for i in 0..v.len() {
        let (s, e) = ((i + 1).saturating_sub(w), i + 1);
        let from = if i == 0 || s >= i {
            (nobs, mean, ssq, comp_add, comp_rem, same, prev) = (0, 0.0, 0.0, 0.0, 0.0, 0, v[s]);
            s
        } else {
            for &x in &v[i.saturating_sub(w)..s] {
                if x == x {
                    nobs -= 1;
                    if nobs != 0 {
                        let prev_mean = mean - comp_rem;
                        let y = x - comp_rem;
                        let t = y - mean;
                        comp_rem = t + mean - y;
                        mean -= t / nobs as f64;
                        ssq -= (x - prev_mean) * (x - mean);
                    } else {
                        mean = 0.0;
                        ssq = 0.0;
                    }
                }
            }
            i
        };
        for &x in &v[from..e] {
            if x == x {
                nobs += 1;
                same = if x == prev { same + 1 } else { 1 };
                prev = x;
                let prev_mean = mean - comp_add;
                let y = x - comp_add;
                let t = y - mean;
                comp_add = t + mean - y;
                mean += t / nobs as f64;
                ssq += (x - prev_mean) * (x - mean);
            }
        }
        out[i] = if nobs >= w as i64 && nobs > 1 {
            let var = if same >= nobs { 0.0 } else { ssq / (nobs - 1) as f64 };
            if var < 0.0 { 0.0 } else { var.sqrt() }
        } else {
            f64::NAN
        };
    }
}

/// pandas 2.3 `ewm(alpha, adjust=False, ignore_na=True).mean()` (aggregations.pyx `ewm`, min_periods 1);
/// `alpha` is the one pandas uses: 1 / (1 + com) with com = (1 - alpha) / alpha.
fn ewm_mean_pd(v: &[f64], alpha: f64, out: &mut [f64]) {
    if v.is_empty() {
        return;
    }
    let old_factor = 1.0 - alpha;
    let mut weighted = v[0];
    let mut nobs = (weighted == weighted) as i64;
    out[0] = if nobs >= 1 { weighted } else { f64::NAN };
    let mut old_wt = 1.0f64;
    for i in 1..v.len() {
        let cur = v[i];
        let observed = cur == cur;
        nobs += observed as i64;
        if weighted == weighted {
            if observed {
                old_wt *= old_factor;
                if weighted != cur {
                    weighted = old_wt * weighted + alpha * cur;
                    weighted /= old_wt + alpha;
                }
                old_wt = 1.0;
            }
        } else if observed {
            weighted = cur;
        }
        out[i] = if nobs >= 1 { weighted } else { f64::NAN };
    }
}

/// pandas 2.3 `rolling(window, min_periods).median()` (`roll_median_c`): median of the non-NaN values.
fn rolling_median_pd(v: &[f64], w: usize, min_periods: usize, out: &mut [f64]) {
    let mut buf: Vec<f64> = Vec::with_capacity(w);
    for i in 0..v.len() {
        buf.clear();
        buf.extend(v[(i + 1).saturating_sub(w)..=i].iter().copied().filter(|x| x == x));
        let n = buf.len();
        out[i] = if n >= min_periods && n > 0 {
            buf.sort_by(|a, b| a.total_cmp(b));
            if n % 2 == 1 { buf[n / 2] } else { (buf[n / 2] + buf[n / 2 - 1]) / 2.0 }
        } else {
            f64::NAN
        };
    }
}

/// Run `kernel` on each group; the pandas kernels first see inf as NaN, as pandas `_prep_values` does.
fn per_group<'py>(
    py: Python<'py>,
    values: &PyReadonlyArray1<'py, f64>,
    offsets: &PyReadonlyArray1<'py, i64>,
    inf_as_nan: bool,
    kernel: impl Fn(&[f64], &mut [f64]) + Sync,
) -> PyResult<Bound<'py, PyArray1<f64>>> {
    let (x, off) = (values.as_slice()?, offsets.as_slice()?);
    let spans = groups(x.len(), off)?;
    let out = py.detach(|| {
        let x: Vec<f64> = if inf_as_nan { x.iter().map(|&a| if a.is_infinite() { f64::NAN } else { a }).collect() } else { x.to_vec() };
        let mut out = vec![f64::NAN; x.len()];
        for (a, b) in spans {
            kernel(&x[a..b], &mut out[a..b]);
        }
        out
    });
    Ok(out.into_pyarray(py))
}

fn check_window(window: usize) -> PyResult<()> {
    if window == 0 {
        return Err(PyValueError::new_err("window must be at least 1"));
    }
    Ok(())
}

#[pyfunction]
fn rolling_max_drawdown<'py>(py: Python<'py>, prices: PyReadonlyArray1<'py, f64>, offsets: PyReadonlyArray1<'py, i64>, window: usize) -> PyResult<Bound<'py, PyArray1<f64>>> {
    check_window(window)?;
    per_group(py, &prices, &offsets, false, |g, o| max_drawdown(g, window, o))
}

#[pyfunction]
fn rolling_mean<'py>(py: Python<'py>, values: PyReadonlyArray1<'py, f64>, offsets: PyReadonlyArray1<'py, i64>, window: usize) -> PyResult<Bound<'py, PyArray1<f64>>> {
    check_window(window)?;
    per_group(py, &values, &offsets, true, |g, o| rolling_mean_pd(g, window, o))
}

#[pyfunction]
fn rolling_std<'py>(py: Python<'py>, values: PyReadonlyArray1<'py, f64>, offsets: PyReadonlyArray1<'py, i64>, window: usize) -> PyResult<Bound<'py, PyArray1<f64>>> {
    check_window(window)?;
    per_group(py, &values, &offsets, true, |g, o| rolling_std_pd(g, window, o))
}

#[pyfunction]
fn ewm_mean<'py>(py: Python<'py>, values: PyReadonlyArray1<'py, f64>, offsets: PyReadonlyArray1<'py, i64>, alpha: f64) -> PyResult<Bound<'py, PyArray1<f64>>> {
    if !(alpha > 0.0 && alpha <= 1.0) {
        return Err(PyValueError::new_err("alpha must satisfy 0 < alpha <= 1"));
    }
    per_group(py, &values, &offsets, true, |g, o| ewm_mean_pd(g, alpha, o))
}

#[pyfunction]
fn rolling_median<'py>(py: Python<'py>, values: PyReadonlyArray1<'py, f64>, offsets: PyReadonlyArray1<'py, i64>, window: usize, min_periods: usize) -> PyResult<Bound<'py, PyArray1<f64>>> {
    check_window(window)?;
    if min_periods > window {
        return Err(PyValueError::new_err("min_periods must be <= window"));
    }
    per_group(py, &values, &offsets, true, |g, o| rolling_median_pd(g, window, min_periods, o))
}

/// Pairwise-complete Pearson correlation of the columns of `matrix` (rows = dates): pandas 2.3
/// `DataFrame.corr(min_periods=...)` (algos.pyx `nancorr`, Welford), the same float operations in
/// the same order. A pair needs both values finite; fewer than `min_periods` pairs or a zero
/// divisor is NaN. Cells are independent, so `threads` changes only the speed.
#[pyfunction]
fn nancorr<'py>(py: Python<'py>, matrix: PyReadonlyArray2<'py, f64>, min_periods: usize, threads: usize) -> PyResult<Bound<'py, PyArray2<f64>>> {
    let a = matrix.as_array();
    let (n, k) = (a.shape()[0], a.shape()[1]);
    let cols: Vec<Vec<f64>> = (0..k).map(|j| a.column(j).to_vec()).collect();
    let pool = rayon::ThreadPoolBuilder::new().num_threads(threads.max(1)).build().map_err(|e| PyValueError::new_err(e.to_string()))?;
    let out = py.detach(|| {
        let rows: Vec<Vec<f64>> = pool.install(|| {
            (0..k)
                .into_par_iter()
                .map(|xi| {
                    let x = &cols[xi];
                    (0..=xi)
                        .map(|yi| {
                            let y = &cols[yi];
                            let (mut nobs, mut meanx, mut meany, mut ssqdmx, mut ssqdmy, mut covxy) = (0usize, 0.0f64, 0.0f64, 0.0f64, 0.0f64, 0.0f64);
                            for i in 0..n {
                                let (vx, vy) = (x[i], y[i]);
                                if vx.is_finite() && vy.is_finite() {
                                    nobs += 1;
                                    let dx = vx - meanx;
                                    let dy = vy - meany;
                                    meanx += 1.0 / nobs as f64 * dx;
                                    meany += 1.0 / nobs as f64 * dy;
                                    ssqdmx += (vx - meanx) * dx;
                                    ssqdmy += (vy - meany) * dy;
                                    covxy += (vx - meanx) * dy;
                                }
                            }
                            if nobs < min_periods {
                                return f64::NAN;
                            }
                            let divisor = (ssqdmx * ssqdmy).sqrt();
                            if divisor != 0.0 { covxy / divisor } else { f64::NAN }
                        })
                        .collect()
                })
                .collect()
        });
        let mut r = Array2::from_elem((k, k), f64::NAN);
        for (xi, row) in rows.iter().enumerate() {
            for (yi, &v) in row.iter().enumerate() {
                r[[xi, yi]] = v;
                r[[yi, xi]] = v;
            }
        }
        r
    });
    Ok(out.into_pyarray(py))
}

#[pymodule]
fn etf_kernels(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(rolling_max_drawdown, m)?)?;
    m.add_function(wrap_pyfunction!(rolling_mean, m)?)?;
    m.add_function(wrap_pyfunction!(rolling_std, m)?)?;
    m.add_function(wrap_pyfunction!(ewm_mean, m)?)?;
    m.add_function(wrap_pyfunction!(rolling_median, m)?)?;
    m.add_function(wrap_pyfunction!(nancorr, m)?)?;
    m.add_function(wrap_pyfunction!(momentum::momentum_risk_at_cutoffs, m)?)?;
    m.add_function(wrap_pyfunction!(as_traded::as_traded_month_end_series, m)?)?;
    m.add_function(wrap_pyfunction!(pit::pit_cost_lookup, m)?)?;
    m.add_function(wrap_pyfunction!(pit::latest_known_per_cutoff, m)?)?;
    m.add_function(wrap_pyfunction!(returns::trailing_price_ratios, m)?)?;
    Ok(())
}
