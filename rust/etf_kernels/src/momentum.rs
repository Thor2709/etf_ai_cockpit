//! Point-in-time momentum/risk selection per cut-off (rank validation): which stored row each instrument's
//! indicators read at each cut-off, or why it has none. The indicator values stay in numpy/pandas.
use crate::groups;
use numpy::ndarray::Array2;
use numpy::{IntoPyArray, PyArray2, PyReadonlyArray1};
use pyo3::prelude::*;

const OK: i8 = 0;
const ABSENT: i8 = 1;
const NOT_PREFIX: i8 = 2;
const INVALID: i8 = 3;
const SHORT: i8 = 4;
const STALE: i8 = 5;

/// Rows sorted by (id, day, known) with group `offsets`; cut-offs as (`cut_day`, `cut_stamp`). When an instrument's
/// days rise strictly and its knowledge stamps never fall, the rows known at a cut-off are a prefix of its rows:
/// status OK reads `entry_row` (the prefix end), the others name the reason (ABSENT: no known row; NOT_PREFIX: a
/// revision or later-stamped row, so the caller keeps the per-cut-off path; INVALID: a close not > 0 in the prefix;
/// SHORT: fewer than `needed` rows; STALE: last day more than `max_stale_days` before the cut-off day).
#[pyfunction]
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
pub fn momentum_risk_at_cutoffs<'py>(
    py: Python<'py>,
    day: PyReadonlyArray1<'py, i64>,
    known: PyReadonlyArray1<'py, i64>,
    close: PyReadonlyArray1<'py, f64>,
    offsets: PyReadonlyArray1<'py, i64>,
    cut_day: PyReadonlyArray1<'py, i64>,
    cut_stamp: PyReadonlyArray1<'py, i64>,
    needed: usize,
    max_stale_days: i64,
) -> PyResult<(Bound<'py, PyArray2<i64>>, Bound<'py, PyArray2<i8>>)> {
    let (day, known, close) = (day.as_slice()?, known.as_slice()?, close.as_slice()?);
    let (cut_day, cut_stamp) = (cut_day.as_slice()?, cut_stamp.as_slice()?);
    if known.len() != day.len() || close.len() != day.len() || cut_stamp.len() != cut_day.len() {
        return Err(pyo3::exceptions::PyValueError::new_err("array lengths differ"));
    }
    let spans = groups(day.len(), offsets.as_slice()?)?;
    let mut rows = Array2::from_elem((spans.len(), cut_day.len()), -1i64);
    let mut status = Array2::from_elem((spans.len(), cut_day.len()), NOT_PREFIX);
    for (g, &(a, b)) in spans.iter().enumerate() {
        let (d, k) = (&day[a..b], &known[a..b]);
        if d.windows(2).any(|w| w[1] <= w[0]) || k.windows(2).any(|w| w[1] < w[0]) {
            continue;
        }
        let first_bad = close[a..b].iter().position(|&c| !(c > 0.0)).unwrap_or(b - a);
        for (j, (&cd, &cs)) in cut_day.iter().zip(cut_stamp).enumerate() {
            let end = k.partition_point(|&x| x <= cs).min(d.partition_point(|&x| x <= cd));
            status[[g, j]] = if end == 0 {
                ABSENT
            } else if first_bad < end {
                INVALID
            } else if end < needed {
                SHORT
            } else if cd - d[end - 1] > max_stale_days {
                STALE
            } else {
                rows[[g, j]] = (a + end - 1) as i64;
                OK
            };
        }
    }
    Ok((rows.into_pyarray(py), status.into_pyarray(py)))
}
