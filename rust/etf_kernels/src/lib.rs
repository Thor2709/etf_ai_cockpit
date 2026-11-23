//! Compiled kernels of the ETF AI Cockpit. Each kernel is the one production path of its calculation;
//! the former numpy/pandas form lives only in the tests as the oracle (bit-exact parity).
//! Per-instrument kernels take a frame sorted by (id, date) and group offsets: group g is the
//! contiguous row range [offsets[g], offsets[g + 1]).
use numpy::{IntoPyArray, PyArray1, PyReadonlyArray1};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

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

#[pymodule]
fn etf_kernels(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(rolling_max_drawdown, m)?)?;
    Ok(())
}
