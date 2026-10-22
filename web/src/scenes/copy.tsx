import type { ReactNode } from "react";
import { Claim } from "../data/load";

// The words of the Experience, one entry per beat. Every figure is a <Claim>: the display string
// written by the Python export from the frozen bundles, never a number typed into the copy.

export interface BeatCopy {
  h?: ReactNode;
  /** a short line set larger than the body, straight under the heading */
  lead?: ReactNode;
  body: ReactNode;
}

export const COPY: Record<string, BeatCopy> = {
  prologue: {
    body: null,
  },
  "c-sky": {
    h: "It starts with a cloud.",
    body: (
      <>
        Meteosat saw this cloud deck over southern England on 15 June 2024. Below it lies Sundon, a real electricity network. The orange dots are its <Claim id="n_pv_plants" bare /> solar plants.
      </>
    ),
  },
  "c-play": {
    h: "Real images, fifteen minutes apart.",
    body: (
      <>
        <Claim id="n_frames" bare /> real observations, 08:45 to 12:15 UTC. Between frames the picture only dissolves; nothing is invented.
      </>
    ),
  },
  "c-clear": {
    h: "Just after 11:00, the sky opens.",
    body: (
      <>
        The cloudy share of the field falls from <Claim id="cloudy_frac_start" /> to <Claim id="cloudy_frac_end" />. Over the 6 MW plant the clear-sky index jumps from <Claim id="kc_plant_1100" /> to <Claim id="kc_plant_1130" />.
      </>
    ),
  },
  "e-wipe": {
    h: "Thirty minutes. A dramatic change.",
    body: <>Drag across the two observations. Satellite radiation, turned into power at every registered plant, gives the local fleet's estimated output.</>,
  },
  "e-curve": {
    h: (
      <>
        <Claim id="fleet_pv_delta" /> in half an hour.
      </>
    ),
    body: (
      <>
        The <Claim id="fleet_capacity" /> fleet goes from a quarter of capacity to almost all of it. A satellite estimate, not a meter reading, for the whole fleet, not the 6 MW plant we isolate later.
      </>
    ),
  },
  "g-states": {
    h: "The weather changes the grid.",
    body: (
      <>
        Sundon, rebuilt from UK Power Networks open data: <Claim id="n_buses" bare /> buses, <Claim id="n_branches" bare /> branches, checked against measured circuits. An AC power-flow reconstruction gives the power it draws from the national grid.
      </>
    ),
  },
  "g-why": {
    h: "But how much is actually solar?",
    body: <>Less than it looks: demand fell and the battery swung from charging to supplying at the same time as the sun came out.</>,
  },
  "g-freeze": {
    h: "Now freeze the grid at 11:00.",
    body: (
      <>
        Keep demand and the battery as they were. Change one thing: give the 6 MW plant its clear-sky output, <Claim id="plant_pv_obs_1100" /> → <Claim id="plant_pv_clear_1100" />. What would happen if the sky were clear?
      </>
    ),
  },
  "j-zero": {
    h: "Out of the box, GENCO got the direction wrong.",
    body: (
      <>
        Can a grid foundation model, pretrained on synthetic networks, answer that? First, the simplest question, averaged over <Claim id="n_states" bare /> real half-hours: how much power does Sundon draw from the national grid? The physics says power flows <em>in</em>; the original GENCO has it flowing <em>out</em>.
      </>
    ),
  },
  "j-network": {
    h: "First, we taught it the network.",
    body: (
      <>
        Fine-tuning on synthetic Sundon states fixed the direction (E5). Widening those states to the real operating range (E5b) brought the average import to <Claim id="import_mean_E5b" />, against <Claim id="import_mean_AC" /> for the physics. Synthetic data only.
      </>
    ),
  },
  "j-shift": {
    h: "The right amount was not enough.",
    body: <>Getting the amount of imported electricity right wasn't enough. We also needed GENCO to understand what happens when solar generation changes.</>,
  },
  "i-cf": {
    h: "Then we taught it to respond to solar.",
    body: (
      <>
        Back to 11:00 on 15 June. Give the 6 MW plant its clear-sky output and hold everything else fixed. Ordinary fine-tuning (E5c) barely reacts. A new training signal, pairs of synthetic AC states that differ in one input, makes E5d move like the physics.
      </>
    ),
  },
  "i-slope": {
    h: (
      <>
        Not once: across <Claim id="n_states" bare /> half-hours.
      </>
    ),
    body: (
      <>
        One moment could be luck. Fitted over all <Claim id="n_states" bare /> reconstructed half-hours, the sensitivity says how much import changes per extra MW of solar, from ordinary fine-tuning (E5c) to response-aware training (E5d). On held-out synthetic pairs, a matched run without the new training signal stayed blind.
      </>
    ),
  },
  "j-two": {
    h: "Two models. Two different strengths.",
    lead: "One unresolved challenge.",
    body: (
      <>
        E5b came closer to the physics on the absolute grid state: how much is imported, and the power balance. E5d reproduced the solar response far more accurately, but it did not keep E5b's absolute accuracy. Neither model does both, and only one of three E5d training seeds learned the response this well.
      </>
    ),
  },
  "j-replicate": {
    h: "On a second network, the pattern recurred.",
    body: (
      <>
        Aylesbury East: <Claim id="g2_buses" bare /> buses, <Claim id="g2_solar_mw" /> of solar and <Claim id="g2_wind_mw" /> of wind. GENCO was fine-tuned again from the same starting point. Ordinary fine-tuning stayed largely blind to solar; response-aware training recovered the physical response in <Claim id="g2_D_ok_seeds" bare /> training seeds.
      </>
    ),
  },
  "v-value": {
    h: "Putting a value on the clouds.",
    lead: (
      <>
        One <Claim id="plant_capacity" bare /> MW solar plant, not all of Sundon's solar.
      </>
    ),
    body: (
      <>
        For each evaluated half-hour, we compare the reconstructed electricity grid with the plant generating under observed satellite-derived conditions and under hypothetical clear skies. We calculate the difference in imported electricity and value that energy using actual historical Elexon market prices.
      </>
    ),
  },
  "v-half": {
    h: "One half-hour, worked through.",
    body: (
      <>
        11:00–11:30 UTC is one of the <Claim id="day_periods" bare /> half-hours in the day's total. Scrub the chart for any other; each has its own price, from <Claim id="day_apx_min" /> to <Claim id="day_apx_max" /> that day.
      </>
    ),
  },
  "v-season": {
    h: "The same plant, all season.",
    body: (
      <>
        The same calculation for the same plant, repeated over every evaluated half-hour of the season. A different time scale, not the 15 June total multiplied, and a net total: in <Claim id="cloud_neg_periods" bare /> half-hours the satellite-derived output exceeded the modelled clear-sky estimate, and those count against it.
      </>
    ),
  },
};

export const PROLOGUE = [
  "Imagine a cloud moving across a solar farm.",
  "It might seem like a small weather event.",
  "But that cloud changes how much electricity is generated, how much power the network needs to import, and the economic value of that energy.",
  "What if we could connect all those effects, starting directly from satellite observations?",
];
