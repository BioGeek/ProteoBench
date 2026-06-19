InstaNovo v1.2.2 was run using the latest public pretrained InstaNovo checkpoints available to this release. No model training, fine-tuning, calibration, or parameter optimization was performed using the ProteoBench De Novo DDA-HCD benchmark spectra or labels.

Checkpoint URLs:

- InstaNovo transformer model `instanovo-v1.2.0`: `https://github.com/instadeepai/InstaNovo/releases/download/1.2.0/instanovo-v1.2.0.ckpt`
- InstaNovo+ diffusion/refinement model `instanovoplus-v1.1.0`: `https://github.com/instadeepai/InstaNovo/releases/download/1.1.3/instanovoplus-v1.1.0.ckpt`

The public model training data reported by the InstaNovo project includes ProteomeTools Part I (PXD004732), Part II (PXD010595), and Part III (PXD021013); PRIDE datasets PXD000666, PXD000867, PXD001839, PXD003155, PXD004364, PXD004612, PXD005230, PXD006692, PXD011360, PXD011536, PXD013543, PXD015928, PXD016793, PXD017671, PXD019431, PXD019852, PXD026910, and PXD027772; Massive-KB v1; and an additional phosphorylation dataset that is not publicly released.

The benchmark run evaluated six documented inference modes: greedy search, beam search with 10 beams, knapsack beam search with 10 beams, and the same three searches followed by InstaNovo+ refinement. The submitted datapoint corresponds to the selected best-performing inference mode after reviewing all ProteoBench metrics. Exact checkpoint identifiers, beam count, knapsack setting, refinement setting, and command line are provided in the accompanying run configuration and metrics summary.
