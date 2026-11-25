//! As-traded closes of one instrument's stored bars per version (shadow rank validation): the decision-time close and
//! the month-end series, each restored to traded units by the later splits among the bars the version knows.
use numpy::{IntoPyArray, PyArray1, PyReadonlyArray1};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

const OK: i8 = 0;
const UNEVIDENCED: i8 = 1;
const BAD_CLOSE: i8 = 2;
const SPLIT_INVALID: i8 = 3;
const RESTORED_BAD: i8 = 4;
const ABSENT: i8 = 5;

struct Bars<'a> {
    close: &'a [f64],
    split: &'a [f64],
    last_unevidenced: Vec<i64>, // per row: the last row at or before it without action evidence (-1 none)
    first_invalid: usize,       // the first split that is not finite or negative (len when none)
    events: Vec<usize>,         // the rows with a non-zero split
}

impl Bars<'_> {
    /// The as-traded close of row `r` when the version knows rows [0, end), checked in the Python order: a row on or
    /// before the last unevidenced row, a close not finite or <= 0, any invalid split; else the close times the
    /// later non-zero splits in (r, end), multiplied left to right (`math.prod`), which must be finite and > 0.
    fn close_at(&self, end: usize, r: usize) -> (f64, i8) {
        if self.last_unevidenced[end - 1] >= r as i64 {
            return (f64::NAN, UNEVIDENCED);
        }
        let close = self.close[r];
        if !close.is_finite() || close <= 0.0 {
            return (f64::NAN, BAD_CLOSE);
        }
        if self.first_invalid < end {
            return (f64::NAN, SPLIT_INVALID);
        }
        let mut factor = 1.0f64;
        for &e in &self.events[self.events.partition_point(|&e| e <= r)..self.events.partition_point(|&e| e < end)] {
            factor *= self.split[e];
        }
        let value = close * factor;
        if !value.is_finite() || value <= 0.0 {
            return (f64::NAN, RESTORED_BAD);
        }
        (value, OK)
    }
}

/// One instrument's bars on strictly rising days; `month` = each bar's calendar month index. Version q knows the first
/// `bars_end[q]` bars, of which the first `known_end[q]` are known at its decision time, in month `decision_month[q]`.
/// Returns per version the price close (bar `known_end - 1`; ABSENT when none) as value and status, and the month-end
/// series (the last bar with a non-NaN close of each month before the decision month among the known bars, kept when
/// its status is OK) as `offsets` (q + 1) into `row` and `value`.
#[pyfunction]
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
pub fn as_traded_month_end_series<'py>(
    py: Python<'py>,
    close: PyReadonlyArray1<'py, f64>,
    split: PyReadonlyArray1<'py, f64>,
    evidenced: PyReadonlyArray1<'py, bool>,
    month: PyReadonlyArray1<'py, i64>,
    bars_end: PyReadonlyArray1<'py, i64>,
    known_end: PyReadonlyArray1<'py, i64>,
    decision_month: PyReadonlyArray1<'py, i64>,
) -> PyResult<(
    Bound<'py, PyArray1<f64>>,
    Bound<'py, PyArray1<i8>>,
    Bound<'py, PyArray1<i64>>,
    Bound<'py, PyArray1<i64>>,
    Bound<'py, PyArray1<f64>>,
)> {
    let (close, split, evidenced, month) = (close.as_slice()?, split.as_slice()?, evidenced.as_slice()?, month.as_slice()?);
    let (bars_end, known_end, decision_month) = (bars_end.as_slice()?, known_end.as_slice()?, decision_month.as_slice()?);
    let n = close.len();
    if split.len() != n || evidenced.len() != n || month.len() != n {
        return Err(PyValueError::new_err("bar array lengths differ"));
    }
    let q = bars_end.len();
    if known_end.len() != q || decision_month.len() != q {
        return Err(PyValueError::new_err("version array lengths differ"));
    }
    let mut last = -1i64;
    let bars = Bars {
        close,
        split,
        last_unevidenced: evidenced.iter().enumerate().map(|(i, &e)| { if !e { last = i as i64; } last }).collect(),
        first_invalid: split.iter().position(|&s| !s.is_finite() || s < 0.0).unwrap_or(n),
        events: (0..n).filter(|&i| split[i] != 0.0).collect(),
    };
    let mut price_value = vec![f64::NAN; q];
    let mut price_status = vec![ABSENT; q];
    let (mut offsets, mut row, mut value) = (Vec::with_capacity(q + 1), Vec::new(), Vec::new());
    offsets.push(0i64);
    for j in 0..q {
        let (be, ke) = (bars_end[j], known_end[j]);
        if ke < 0 || ke > be || be as usize > n {
            return Err(PyValueError::new_err("need 0 <= known_end <= bars_end <= bar count"));
        }
        let (end, known) = (be as usize, ke as usize);
        if known > 0 {
            (price_value[j], price_status[j]) = bars.close_at(end, known - 1);
        }
        let mut pending: Option<usize> = None; // the last bar with a non-NaN close in the latest month seen
        for i in (0..known).take_while(|&i| month[i] < decision_month[j]) {
            if close[i].is_nan() {
                continue;
            }
            if let Some(p) = pending.filter(|&p| month[p] != month[i]) {
                if let (v, OK) = bars.close_at(end, p) {
                    row.push(p as i64);
                    value.push(v);
                }
            }
            pending = Some(i);
        }
        if let Some(p) = pending {
            if let (v, OK) = bars.close_at(end, p) {
                row.push(p as i64);
                value.push(v);
            }
        }
        offsets.push(row.len() as i64);
    }
    Ok((
        price_value.into_pyarray(py),
        price_status.into_pyarray(py),
        offsets.into_pyarray(py),
        row.into_pyarray(py),
        value.into_pyarray(py),
    ))
}
