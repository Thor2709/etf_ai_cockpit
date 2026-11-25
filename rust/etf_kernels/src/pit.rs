//! Point-in-time row picks of rank validation: which stored row is the latest known at each cut-off.
//! Rows come sorted by (group, key...) with group `offsets`; the caller keeps every value check in Python.
use crate::groups;
use numpy::{IntoPyArray, PyArray1, PyReadonlyArray1};
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
