//! Point-in-time row picks of rank validation: which stored row is the latest known at each cut-off.
//! Rows come sorted by (group, key...) with group `offsets`; the caller keeps every value check in Python.
use crate::groups;
use numpy::ndarray::Array2;
use numpy::{IntoPyArray, PyArray1, PyArray2, PyReadonlyArray1};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// Round-trip cost per query (`q_group`, `q_cut`): rows sorted by (group, known); the rows known by the cut-off
/// (`known <= q_cut`) give the latest stamp; exactly one row at that stamp gives its `cost`, else NaN (also for
/// no known row, `q_group < 0`, or a cost the caller marked NaN as invalid).
#[pyfunction]
pub fn pit_cost_lookup<'py>(
    py: Python<'py>,
    known: PyReadonlyArray1<'py, i64>,
    cost: PyReadonlyArray1<'py, f64>,
    offsets: PyReadonlyArray1<'py, i64>,
    q_group: PyReadonlyArray1<'py, i64>,
    q_cut: PyReadonlyArray1<'py, i64>,
) -> PyResult<Bound<'py, PyArray1<f64>>> {
    let (known, cost, q_group, q_cut) = (known.as_slice()?, cost.as_slice()?, q_group.as_slice()?, q_cut.as_slice()?);
    if cost.len() != known.len() || q_cut.len() != q_group.len() {
        return Err(PyValueError::new_err("array lengths differ"));
    }
    let spans = groups(known.len(), offsets.as_slice()?)?;
    let mut out = vec![f64::NAN; q_group.len()];
    for (j, (&g, &cut)) in q_group.iter().zip(q_cut).enumerate() {
        if g < 0 {
            continue;
        }
        let &(a, b) = spans.get(g as usize).ok_or_else(|| PyValueError::new_err("query group out of range"))?;
        let k = &known[a..b];
        let end = k.partition_point(|&x| x <= cut);
        if end == 0 {
            continue;
        }
        let latest = k[end - 1];
        if end - k.partition_point(|&x| x < latest) == 1 {
            out[j] = cost[a + end - 1];
        }
    }
    Ok(out.into_pyarray(py))
}

/// Latest-known rows per (group, cut-off): rows sorted by (group, `eff`, `known`, input order). The rows usable at
/// cut-off j have `eff <= cut_day[j]` and `known <= cut_stamp[j]`; the greatest (eff, known) among them is a block of
/// equal keys, returned as its first and last sorted row (`first[g, j]`, `last[g, j]`; -1 when no row is usable).
#[pyfunction]
#[allow(clippy::type_complexity)]
pub fn latest_known_per_cutoff<'py>(
    py: Python<'py>,
    eff: PyReadonlyArray1<'py, i64>,
    known: PyReadonlyArray1<'py, i64>,
    offsets: PyReadonlyArray1<'py, i64>,
    cut_day: PyReadonlyArray1<'py, i64>,
    cut_stamp: PyReadonlyArray1<'py, i64>,
) -> PyResult<(Bound<'py, PyArray2<i64>>, Bound<'py, PyArray2<i64>>)> {
    let (eff, known, cut_day, cut_stamp) = (eff.as_slice()?, known.as_slice()?, cut_day.as_slice()?, cut_stamp.as_slice()?);
    if known.len() != eff.len() || cut_stamp.len() != cut_day.len() {
        return Err(PyValueError::new_err("array lengths differ"));
    }
    let spans = groups(eff.len(), offsets.as_slice()?)?;
    let mut first = Array2::from_elem((spans.len(), cut_day.len()), -1i64);
    let mut last = Array2::from_elem((spans.len(), cut_day.len()), -1i64);
    for (g, &(a, b)) in spans.iter().enumerate() {
        let (e, k) = (&eff[a..b], &known[a..b]);
        for (j, (&cd, &cs)) in cut_day.iter().zip(cut_stamp).enumerate() {
            let Some(end) = (0..e.partition_point(|&x| x <= cd)).rev().find(|&i| k[i] <= cs) else {
                continue;
            };
            let mut start = end;
            while start > 0 && e[start - 1] == e[end] && k[start - 1] == k[end] {
                start -= 1;
            }
            first[[g, j]] = (a + start) as i64;
            last[[g, j]] = (a + end) as i64;
        }
    }
    Ok((first.into_pyarray(py), last.into_pyarray(py)))
}
