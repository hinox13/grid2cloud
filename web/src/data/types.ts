// Shapes of the frozen JSON written by scripts/web/export_web_data.py. Numbers are never computed
// here: the browser formats and draws what the Python export wrote.

export type Provenance = "observed" | "derived" | "simulated" | "predicted" | "hypothetical";

export interface Claim {
  id: string;
  value: number | null;
  unit: string;
  display: string;
  provenance: Provenance;
  source: string;
  note: string;
}

export interface Frame {
  t: string;
  served: string;
  file: string;
  bbox: [number, number, number, number]; // lon0, lat0, lon1, lat1
  product: string;
  source_event: string;
  sha256: string;
}

export interface Asset {
  id: string;
  capacity_mw: number;
  kv: number | null;
  lat: number;
  lon: number;
  p_mw: (number | null)[];
  capacity_factor: (number | null)[];
  clearsky_index: (number | null)[] | null;
  ghi_wm2: (number | null)[] | null;
}

export interface FlowState {
  p_ab_mw: (number | null)[];
  loading_pct: (number | null)[];
  vm_pu: (number | null)[];
}

export type ModelId = "AC" | "zero_shot" | "E5" | "E5b" | "E5c" | "E5d";

export interface EventData {
  id: string;
  title: string;
  story: string;
  class_name: string[];
  selection_criteria: string;
  provenance: Record<string, string>;
  source_events: string[];
  event_metrics: Record<string, number | string>[];
  active_pv_capacity_mw: number;
  satellite_step_minutes: number;
  grid_step_minutes: number;
  models: ModelId[];
  frames: Frame[];
  fleet_pv_mw: (number | null)[];
  assets: Asset[];
  plant_id: string;
  grid_slots: string[];
  grid_scenarios: number[];
  summary: Record<ModelId, Record<"import_mw" | "max_loading_pct" | "PBE_mean" | "P_residual" | "V_error" | "branch_P_error", (number | null)[]>>;
  grid_inputs: {
    hv_pv_mw: number[];
    load_incl_battery_mw: number[];
    battery_chap31_mw: number[];
    mean_kc: number[];
    lines_out: string[];
  };
  flows: Record<ModelId, Record<string, FlowState>>;
  edge_ids: string[];
  decomposition: {
    from: string;
    to: string;
    delta: { load_mw: number; chap31_mw: number; pv_injection_mw: number };
    terms: Record<ModelId, { pv: number; load: number; battery: number; total: number }>;
  }[];
}

export interface EventIndexRow {
  event_id: string;
  title: string;
  story: string;
  class_name: string[];
  time_start_utc: string;
  time_end_utc: string;
  n_frames: number;
  n_grid_slots: number;
}

export interface NetNode {
  bus: number;
  key: string;
  label: string;
  members: string[];
  kv: number;
  lat: number | null;
  lon: number | null;
  x: number;
  y: number;
  role: string;
  slack: boolean;
  substation: string;
}

export interface NetEdge {
  id: string;
  a: number;
  b: number;
  from: string;
  to: string;
  kind: "line" | "trafo";
  elements: string[];
  rating_mva: number;
}

export interface Network {
  n_buses_model: number;
  n_branches_model: number;
  nodes: NetNode[];
  edges: NetEdge[];
  layout: {
    bands: { label: string; y0: number; y1: number }[];
    groups: { label: string; x: number; y: number; anchor?: string }[];
    busbars: Record<string, { y: number }>;
  };
}

export interface ModelInfo {
  id: Exclude<ModelId, "AC">;
  label: string;
  short: string;
  experiment: string;
  name: string;
  exp: string;
  about: string;
  verdict: string;
  finding: string;
  ladder_added: string;
  ladder_outcome: string;
  selected_run?: string;
  selection_flagged?: boolean;
  checkpoint_sha256?: string;
  normalizer_sha256?: string;
  checkpoint_ref?: string;
  registry: string | null;
}

export type EvolutionRow = Record<string, number | string | [number, number]> & { model: string };

export interface ModelsData {
  models: ModelInfo[];
  ac: { name: string; about: string; verdict: string };
  evolution: EvolutionRow[];
  ols_coefficients_s1: Record<string, { intercept: number; load: number; chap31: number; pv: number }>;
  published_tables: Record<string, string>;
}

export interface PvResponse {
  scenario: number[];
  t: string[];
  [col: string]: number[] | string[];
}

export interface CloudImpact {
  periods: {
    slot: string[];
    settlement_date: string[];
    settlement_period: number[];
    plant_pv_mw: number[];
    plant_pv_clear_mw: number[];
    import_AC_observed_mw: number[];
    import_AC_clear_sky_mw: number[];
    import_AC_no_plant_mw: number[];
    import_E5c_observed_mw: number[];
    import_E5c_clear_sky_mw: number[];
    import_E5d_observed_mw: number[];
    import_E5d_clear_sky_mw: number[];
    apx_gbp_per_mwh: number[];
    apx_volume_mwh: number[];
    system_price_gbp_per_mwh: number[];
    fleet_pv_mw: (number | null)[];
  };
  derived: { note: string } & Record<`cloud_${"AC" | "E5c" | "E5d"}_${"mw" | "mwh" | "gbp"}` | "plant_pv_mwh" | "plant_pv_clear_mwh" | "import_obs_mwh" | "import_clear_mwh" | "import_obs_gbp" | "import_clear_gbp", number[]>;
  season: {
    periods_valued: number;
    pv_attributed: Record<string, Record<string, number>>;
    cloud_attributed: Record<string, Record<string, number>>;
    absolute_mode_diagnostic: Record<string, Record<string, number>>;
    daily_context: Record<string, number | string>;
    [k: string]: unknown;
  };
  /** UTC dates (YYYY-MM-DD) with at least one evaluated half-hour, April–September 2024 */
  season_dates: string[];
  definitions: Record<string, string>;
  sources: { name: string; endpoint?: string; licence: string; licence_url?: string; attribution?: string }[];
  apx_gap: { slot_utc: string; settlement_period: number; value_bound_gbp: number; source: string };
}

export interface Attribution {
  sources: { source_id: string; licence: string; licence_url: string; attribution: string; modified: boolean }[];
  gate_decisions: Record<string, string | boolean>[];
  modified_notice: string;
  economic_sources: CloudImpact["sources"];
  economic_gate_decisions: Record<string, string | boolean>[];
  footer: string;
  bundle: { schema_version: string; git_commit: string };
}
