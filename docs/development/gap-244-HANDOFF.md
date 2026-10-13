# Issue #244 safe-point handoff

## Implemented

- Explicit disclosure placeholders (`not disclosed`, `unavailable`, `unknown`, `not applicable`, and equivalent bounded forms) remain visible in parser candidate evidence but produce `status=unavailable` and no extracted value.
- A report that labels one of those placeholders as extracted cannot pass the existing reviewability check. Structural candidates also reject placeholder values from local supplemental and report channels.
- Projection status follows required applicable fields and always treats missing derivative disclosure as an assessment gap. Non-applicable collateral and lending terms remain visible as unknown fields without reducing coverage for a physical, non-lending example.
- Missing numeric stress evidence remains `unavailable` with its reason code; no numeric value is filled in.

## Defaults and limits

- Placeholder recognition is conservative and English-only, consistent with the existing report template. Text beginning with an explicit unavailable marker is treated as unavailable even if it continues with explanatory text.
- Unknown disclosure branches are not inferred as active. Their missing status remains explicit; missing derivatives are included in the projection's assessment status because derivatives can activate counterparty and collateral requirements.
- Existing applicability and confidence weights are unchanged. Synthetic fixtures test the machinery only; accepted disclosure coverage, exhaustive legal review, production renderer behavior, and real-data acceptance remain for the owner to specify and validate.
- Execution authority remains disabled.
