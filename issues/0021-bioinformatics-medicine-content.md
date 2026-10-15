---
status: done
kind: content
---

# Bioinformatics and medicine: genes, proteins, technologies, diseases

Wish of the user (2026-10-15): new topics "Genes" and "Proteins" under bioinformatics, with function, aliases, discovery history and the proteins a gene encodes; measurement technologies and platforms for single-cell and bulk expression with all subtypes; and diseases relevant to their work at a university hospital (liver cirrhosis and fatty liver disease, PDAC, organ transplantation, cancer in general) with terms, treatments and staging systems.
Priority matters most: the important ~100 genes (oncogenes, tumour suppressors, cell cycle, apoptosis, immune regulation) rather than all 20,000.
Later the same day: every item should carry a mnemonic or anecdote whenever one helps.

2026-10-15: Done, written by five LLM agents from one spec and merged by hand.

- 1,090 items in space `concepts` under `bioinformatics/`: cancer genes with proteins (285), immune/transplant/liver/pancreas genes with proteins (267), technologies (148), liver disease and transplantation (199), cancer and PDAC (190); see content/README.md.

- Priorities span 0–100 (about 60 items at 95+); about 80 % of the items have a mnemonic or an anecdote, every item with priority 80+ has one.

- A course "Bioinformatics & medicine" (`content/curricula/bioinformatics.json`) with 5 stages and 67 units makes them playable on the level map.

- Merging: MTOR and STAT3 kept once (cancer genes), CA19-9 once (cancer/PDAC), MYC merged into the existing PhD item `myc`, the AFP protein into the clinical `alpha-fetoprotein` item; 149 aliases dropped because they named another item (typically a gene listing its protein's name, which would have made the import treat the protein as the gene); proteins named like their gene symbol got " protein" in the label.

- Facts the agents flagged as worth a spot-check (recent approvals, version-dependent criteria) are worded with their year or hedged in the text.
