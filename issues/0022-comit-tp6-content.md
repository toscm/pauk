---
status: done
kind: content
---

# CoMIT TP6 content: PDAC biology, statistics, papers, models and datasets

Wish of the user (2026-10-15): knowledge items and questions on the PDAC background of CoMIT TP6, covering the terms needed to speak confidently about it (RNAi, IRG, epithelial and ductal cells, ...), the statistics behind it, and the published papers, models and data sets: who published which method and which data set, and where to find the data.

2026-10-15: Done, written by five LLM agents from one spec and merged by hand.

- Four public deck/items pairs in space `concepts` under `comit/tp6/`: biology (78 items, 85 cards), statistics (81, 102), literature (40, 70), datasets (51, 61); every card is linked to an item.

- Course "CoMIT TP6 (PDAC)" (`content/curricula/comit-tp6.json`) with 5 stages and 21 units.

- Merging: `pdacr-data-package` folded into `pdacr`; ABSOLUTE, ESTIMATE and virtual microdissection kept once (literature); existing items such as `tumour-purity`, `hazard-ratio`, `lasso` and the PDAC genes are linked, not repeated.

- The public repo holds only published knowledge.
  Everything about the project's own work is kept in private files outside the repo and imported only into the live instance (2026-10-15: cards and item passages about the project moved there before the first commit).

- The card on raw counts and differential expression (and the item `raw-read-counts`) overstated that DE tests need raw counts; corrected on 2026-10-15: count models matter most with few samples, limma-voom works on log-CPM with precision weights, and with many samples per group a t-test or Wilcoxon test of log-CPM is adequate (Li et al. 2022, Genome Biology).

- Facts the agents flagged as written from general knowledge rather than the books (e.g. Panc-1 genotype, Peng 2019 cell counts, some anecdotes) are worth a spot-check.

- Imported into the live instance on 2026-10-15.
  The first import hit the alias trap of issues/0023 and overwrote seven items; they were restored from their files and the misdirected links removed, and eight keys and five labels were changed so that neither the key nor the label slug (parentheticals dropped, see `Norm::slug`) is an alias of another item.
