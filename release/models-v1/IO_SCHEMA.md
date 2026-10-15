# Input / output schema (E5c and E5d checkpoints)

**Architecture.** GraphKit `GNS_heterogeneous`: hidden size 48, 12 layers, 8 attention heads, 20,069,187 parameters (float32). The config is in `graphkit_predict_config.yaml`.

**Task.** GraphKit `PowerFlow`. Both checkpoints load into the unchanged task: E5d's response loss added no parameter.

**Network.** The models were trained on **one network only**, Sundon 33 kV:
- 37 buses; slack (REF) = bus 22; 43 branches;
- supplied as `sundon_33kv.m` (MATPOWER) with the data;
- out-of-service branches appear with zero admittance.

**They are not general-purpose power-flow models.**

## Inputs: GraphKit raw tables (one row per scenario × element)

`<data_path>/sundon_33kv/raw/{bus_data,branch_data,gen_data,y_bus_data,runtime_data}.parquet`, written by gridfm-datakit 1.1.0.

| Table | Fields GENCO uses | Units |
|---|---|---|
| `bus_data` | `Pd`, `Qd`, `Pg`, `Qg`, `Vm`, `Va`, bus type `PQ`/`PV`/`REF`, `vn_kv`, Vm limits, shunts `GS`/`BS` | MW, MVAr, pu, **degrees** in the raw table |
| `gen_data` | per-generator `p_mw`, `q_mvar`, limits, `is_slack_gen` | MW, MVAr |
| `branch_data` | from/to bus, `Yff`/`Yft`/`Ytf`/`Ytt` (real, imag), tap, shift, rating, status | pu on 100 MVA |

**Generator-aware encoding is required.**
- **What the models expect:** the three Leighton Buzzard PV/wind generators (LBUZ31/32/33, buses 8, 9 and 10) are explicit generator nodes with known Pg on PQ buses.
- **What not to do:** don't encode that generation as negative load, the encoding GENCO saw before E5c. The models were trained on the generator-aware form, and the other gives wrong results.
- **Known decoder inconsistency (both models):** GraphKit's internal physics decoder sets Pg = 0 at PQ buses. So this known generation is missing from the model's *internal* residual feedback, although it is present in the inputs and in evaluation. It was found after both models were frozen. See the model cards.

**Normalisation.**
- **Use only the `normalizer_stats.pt` shipped with the same checkpoint** (`HeteroDataMVANormalizer`, fitted on that run's 10,000 training states).
- E5c's baseMVA is 36.722 and E5d's is 36.741; they are not interchangeable.
- Pass it with `--normalizer_stats` to `gridfm_graphkit predict`.

## Outputs: `gridfm_graphkit predict`

**`sundon_33kv_predictions.parquet`**, per scenario × bus:
- `Vm_pred` (pu), `Va_pred` (**radians**), `Pg_pred`, `Qg_pred` (MW, MVAr);
- the matching `*_target` AC values;
- graphkit's per-bus `active res. (MW)`, `reactive res. (MVar)` and `PBE` (MVA).

**Grid import** = `Pg_pred` at the REF bus (MW, positive = import).

**`sundon_33kv_branch_predictions.parquet`**, per scenario × directed edge: `Pft`, `Qft` (MW, MVAr at the sending end) and their AC targets.
