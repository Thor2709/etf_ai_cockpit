//! Trailing close ratios of the factor-risk return matrix (rank validation factor attribution): the pandas
//! `pivot_table(aggfunc="last")` / `shift(1)` / `dropna(how="all")` / `tail(window)` of `portfolio.factor_risk`.
//! The log of the ratios stays in numpy.
use numpy::ndarray::Array2;
use numpy::{IntoPyArray, PyArray1, PyArray2, PyReadonlyArray1};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// Rows sorted by (`key`, input order); a row passes when `keep[id]`, `day <= cut_day` and `known <= cut_stamp`;
/// only rows before `end` are read (the caller proves no later row passes). The calendar is the distinct keys of
/// passing rows; per (key, id) the value is the close of the last passing row. A ratio row divides each kept id's
/// value by its value on the previous calendar key; a ratio that is not finite and > 0 is NaN, and rows without
/// any such ratio are dropped. Returns the last `window` rows (all when 0), oldest first, as one sorted row
/// position per key and the ratios (rows x kept ids, kept ids in id order).
#[pyfunction]
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
pub fn trailing_price_ratios<'py>(
    py: Python<'py>,
    key: PyReadonlyArray1<'py, i64>,
    day: PyReadonlyArray1<'py, i64>,
    id: PyReadonlyArray1<'py, i64>,
    known: PyReadonlyArray1<'py, i64>,
    close: PyReadonlyArray1<'py, f64>,
    keep: PyReadonlyArray1<'py, bool>,
    cut_day: i64,
    cut_stamp: i64,
    end: usize,
    window: usize,
) -> PyResult<(Bound<'py, PyArray1<i64>>, Bound<'py, PyArray2<f64>>)> {
    let (key, day, id, known, close, keep) = (key.as_slice()?, day.as_slice()?, id.as_slice()?, known.as_slice()?, close.as_slice()?, keep.as_slice()?);
    let n = key.len();
    if [day.len(), id.len(), known.len(), close.len()].iter().any(|&m| m != n) || end > n {
        return Err(PyValueError::new_err("array lengths differ"));
    }
    if id.iter().any(|&g| g < 0 || g as usize >= keep.len()) {
        return Err(PyValueError::new_err("id out of range"));
    }
    let mut column = vec![usize::MAX; keep.len()];
    let mut k = 0;
    for (g, &kept) in keep.iter().enumerate() {
        if kept {
            column[g] = k;
            k += 1;
        }
    }
    let passes = |r: usize| keep[id[r] as usize] && day[r] <= cut_day && known[r] <= cut_stamp;
    // The calendar key below sorted position `from`: (its lowest sorted row, a passing row, values per kept id).
    let read = |from: usize| -> Option<(usize, usize, Vec<f64>)> {
        let top = (0..from).rev().find(|&r| passes(r))?;
        let mut values = vec![f64::NAN; k];
        let mut low = top;
        loop {
            if passes(low) {
                let slot = &mut values[column[id[low] as usize]];
                if slot.is_nan() {
                    *slot = close[low]; // the first seen from the top is the last passing row in input order
                }
            }
            if low == 0 || key[low - 1] != key[top] {
                break;
            }
            low -= 1;
        }
        Some((low, top, values))
    };
    let mut rows: Vec<i64> = Vec::new();
    let mut ratios: Vec<f64> = Vec::new();
    if let Some((mut low, mut row, mut values)) = read(end) {
        while window == 0 || rows.len() < window {
            let Some((prev_low, prev_row, prev_values)) = read(low) else { break };
            let ratio: Vec<f64> = values.iter().zip(&prev_values).map(|(&a, &b)| {
                let r = a / b;
                if r.is_finite() && r > 0.0 { r } else { f64::NAN }
            }).collect();
            if ratio.iter().any(|r| !r.is_nan()) {
                rows.push(row as i64);
                ratios.extend(ratio);
            }
            (low, row, values) = (prev_low, prev_row, prev_values);
        }
    }
    let w = rows.len();
    let mut out = Array2::from_elem((w, k), f64::NAN);
    for (i, chunk) in ratios.chunks(k.max(1)).enumerate().take(w) {
        out.row_mut(w - 1 - i).iter_mut().zip(chunk).for_each(|(o, &v)| *o = v);
    }
    rows.reverse();
    Ok((rows.into_pyarray(py), out.into_pyarray(py)))
}
