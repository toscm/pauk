---
status: open
kind: bug
---

# Bulk item import silently overwrites another item that owns the new key or label as an alias

`PUT /items/bulk` matches by exact identity, and `exactIdentity()` also accepts an alias match on the key or on `Norm::slug(label_md)`.
A new item whose key or label slug happens to be an alias of a different item therefore updates that other item: kind, label, gloss, body, attrs, priority and level are replaced, its links, dirs and aliases are added to the wrong item, and card links of the file go to it.
The response only counts it as `updated`, so nothing tells the importer that a different item was hit.

Found on 2026-10-15 with the CoMIT TP6 content (issues/0022): the new keys `purist`, `cox-model`, `collisson-subtypes`, `bailey-subtypes`, `islets-of-langerhans`, `acinar-cell-carcinoma`, `mcp-counter` and `top-scoring-pairs` were aliases of `moffitt-classical-basal-like`, `hazard-ratio`, `pdac-molecular-subtypes`, `pancreas-anatomy`, `pdac-histological-variants`, `paper-becht-2016` and `paper-geman-2004`.
`Norm::slug` drops parentheticals, so a label like "PurIST (Purity Independent Subtyping of Tumors)" slugs to `purist`, which a client-side check without that rule misses.

Left over, because no endpoint deletes an alias: aliases written onto the wrong items by that import.

- `hazard-ratio`: `cox-regression`, `partial-likelihood`, `proportional-hazards-regression`.

- `moffitt-classical-basal-like`: `purist-classifier`, `purity-independent-subtyping-of-tumors`.

- `pancreas-anatomy`: `endocrine-pancreas`, `pancreatic-islets`.

- `paper-geman-2004`: `gene-pair-classifier`, `relative-expression-ordering`.

- `pdac-molecular-subtypes`: `aberrantly-differentiated-endocrine-exocrine`, `exocrine-like-subtype`, `immunogenic-subtype`, `pancreatic-progenitor-subtype`, `pdassigner`, `qm-pda`, `quasi-mesenchymal-subtype`.

Some of these may have been on the item before (the check compared against the aliases in its content file).

Possible fixes: in bulk mode, treat an alias match whose target has a different key as a conflict (report it, do not update), like the teacher-item conflicts; and add `DELETE /items/{ref}/aliases/{alias}` so stray aliases can be removed.
