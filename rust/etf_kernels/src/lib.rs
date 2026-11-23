//! Compiled kernels of the ETF AI Cockpit. Each kernel is the one production path of its calculation;
//! the former numpy/pandas form lives only in the tests as the oracle (bit-exact parity).
//! Per-instrument kernels take a frame sorted by (id, date) and group offsets: group g is the
//! contiguous row range [offsets[g], offsets[g + 1]).
use numpy::ndarray::Array2;
use numpy::{IntoPyArray, PyArray1, PyArray2, PyReadonlyArray1, PyReadonlyArray2};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rayon::prelude::*;

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

#[pyfunction]
fn rolling_max_drawdown<'py>(py: Python<'py>, prices: PyReadonlyArray1<'py, f64>, offsets: PyReadonlyArray1<'py, i64>, window: usize) -> PyResult<Bound<'py, PyArray1<f64>>> {
    if window == 0 {
        return Err(PyValueError::new_err("window must be at least 1"));
    }
    let (x, off) = (prices.as_slice()?, offsets.as_slice()?);
    let spans = groups(x.len(), off)?;
    let out = py.detach(|| {
        let mut out = vec![f64::NAN; x.len()];
        for (a, b) in spans {
            max_drawdown(&x[a..b], window, &mut out[a..b]);
        }
        out
    });
    Ok(out.into_pyarray(py))
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
    m.add_function(wrap_pyfunction!(nancorr, m)?)?;
    Ok(())
}
