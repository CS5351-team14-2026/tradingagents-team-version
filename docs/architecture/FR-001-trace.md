# REQ-TA-FR-001 — traceability record

- Requirement: `docs/req/requirements.yaml` → REQ-TA-FR-001 (must, implement)
- ADR: `docs/architecture/ADR-002-analysis-profiles.md`
- Approved test plan: [Issue #14](https://github.com/CS5351-team14-2026/tradingagents-team-version/issues/14)
- Pre-change baseline: `03e7d48`, 1407 offline tests passed.
- FR-001 evidence: 71 profile tests. The full offline suite was rerun with
  FR-001 applied to `2438f28` on 2026-11-16. It reported 1478 passed, 6 skipped,
  1 deselected, 24 warnings, and 100 passing subtests.

FR-001-specific tests cite `REQ-TA-FR-001` in their docstrings. The existing
INV-003 regression tests are identified separately below.

## fit_criterion → step → file → test

| fit_criterion clause | Implementation | Tests |
|---|---|---|
| profile in {quick, standard, deep} | `default_config.PROFILE_MAPPING`, `PROFILE_NAMES` | `test_profiles.py::test_profile_names_are_the_approved_three_in_order`, `::test_each_profile_applies_its_approved_mapping[quick/standard/deep]` |
| a valid profile applies the mapping exactly (analysts, debate, risk, tool caps) | `default_config.resolve_profile`; `trading_graph.TradingAgentsGraph` wiring | `test_profiles_graph.py::test_the_graph_uses_the_profile_settings[quick/standard/deep]` |
| invalid profile rejected BEFORE any LLM call, naming legal values | `resolve_profile` raises; graph resolves before `create_tier_client`; `run_analysis` validates first | `test_profiles.py::test_an_unknown_profile_is_rejected_naming_the_legal_values`; `test_profiles_graph.py::test_an_unknown_profile_is_rejected_before_any_client_is_built`; `test_cli_profile.py::test_run_analysis_passes_the_profile_and_shares_one_config` / `::test_an_unknown_profile_fails_before_any_graph_or_prompt`; `::test_the_main_command_forwards_the_profile_flag` (legal value list) |
| unset profile reproduces v0.7.1 defaults exactly | `_resolved_from_defaults`; no env re-read | `test_profiles.py::test_none_reproduces_the_baseline_without_a_profile_key`, `::test_none_honours_environment_folded_defaults`; `test_profiles_graph.py::test_a_legacy_call_keeps_the_config_rounds_without_a_profile`; `test_cli_profile_e2e.py::test_omitted_profile_runs_exactly_the_menu_selection`; `test_cli_profile.py::test_omitted_profile_keeps_the_original_questions`, `::test_omitted_profile_still_maps_depth_to_rounds` |
| explicit settings override the profile per key only | `resolve_profile(explicit=...)` applied per field; CLI `--analysts`/env; Python `selected_analysts` + `explicit_overrides` (latter wins) | `test_profiles.py::test_deep_with_explicit_debate_one_keeps_risk_at_three`, `::test_explicit_analysts_override_only_the_analyst_field`, `::test_several_explicit_fields_override_independently`, `::test_all_four_fields_can_be_overridden`, `::test_no_profile_but_explicit_values_still_apply`; `test_profiles_graph.py::test_explicit_round_override_keeps_the_other_profile_fields`, `::test_a_passed_analyst_list_overrides_the_profile`, `::test_explicit_overrides_analysts_wins_over_a_passed_selection`, `::test_a_base_analyst_set_is_not_recorded_as_an_override`; `test_cli_profile_e2e.py::test_deep_with_a_debate_env_override_shows_the_effective_config`, `::test_an_explicit_analysts_flag_is_recorded` |
| report metadata records requested AND resolved | `run_settings` (`profile_requested`/`profile_overrides`/`profile_resolved`/`max_tool_rounds`); `reporting._header`; `report_html._run_details`; `_log_state` | `test_profiles_report.py::test_run_settings_record_requested_overrides_and_resolved`, `::test_the_state_log_records_requested_overrides_and_resolved`, `::test_the_markdown_report_shows_requested_overrides_and_resolved`, `::test_the_html_report_shows_requested_overrides_and_resolved`, `::test_a_bare_profile_run_records_no_overrides`, `::test_an_explicit_analyst_override_is_recorded_even_when_it_matches`, `::test_a_crypto_filtered_set_shows_in_resolved_but_not_overrides` |

## Extra behaviours verified (design decisions in the ADR)

- CLI `--profile` beats `TRADINGAGENTS_PROFILE`: `test_cli_profile.py::test_profile_flag_beats_the_environment`.
- A selected profile skips the analyst & depth questions and supplies headless config: `test_cli_profile.py::test_a_profile_skips_the_analyst_and_depth_questions`, `::test_a_profile_supplies_analysts_and_rounds_so_they_are_not_gaps`, `::test_a_valid_profile_runs_headless_with_config_omitted`.
- Overrides by source (empty unless user-named; explicit `--analysts` recorded; a Python `selected_analysts` recorded while `explicit_overrides["analysts"]` wins; a CLI auto-selected base set and the crypto filtered list recorded only in `profile_resolved`): `test_profiles_graph.py::test_a_passed_analyst_list_overrides_the_profile`, `::test_explicit_overrides_analysts_wins_over_a_passed_selection`, `::test_a_base_analyst_set_is_not_recorded_as_an_override`; `test_cli_profile_e2e.py::test_a_bare_profile_run_records_no_override`, `::test_an_explicit_analysts_flag_is_recorded`, `::test_the_crypto_filtered_list_shows_in_resolved`.
- Crypto keeps the asset filter; stock mapping unchanged: `test_cli_profile_e2e.py::test_crypto_standard_drops_fundamentals`.
- Terminal shows the effective rounds and drops the stale 3/3 hint: `test_cli_profile_e2e.py::test_deep_with_a_debate_env_override_shows_the_effective_config`, `test_cli_profile.py::test_a_profile_does_not_print_a_stale_round_hint`.
- Checkpoint signature: omitted profile keeps the 03e7d48 signature (tool cap 20 and 7); a real change differs: `test_profiles_graph.py::test_a_legacy_call_keeps_the_03e7d48_signature[20/7]`, `::test_the_pre_change_signature_for_a_fixed_config_is_unchanged`, `::test_an_override_changing_the_tool_cap_changes_the_signature`, `::test_a_profile_that_changes_rounds_yields_a_different_signature`, `::test_quick_and_deep_signatures_differ`.
## REQ-TA-INV-003 — tool-call round limit

The registry marks the invariant as `restate`. FR-001 passes the resolved
`max_tool_rounds` to `GraphSetup`, which enforces the existing cap in
`setup._analyst_graph`.

| Evidence | What it verifies |
|---|---|
| [`test_profiles_graph.py`](../../test/offline/test_profiles_graph.py), `test_the_graph_uses_the_profile_settings` | Each profile passes its configured per-analyst tool-call cap to the graph. |
| [`test_graph_end_to_end.py`](../../test/offline/test_graph_end_to_end.py), `test_an_analyst_that_keeps_calling_tools_writes_its_report_at_the_limit` | With a three-round cap, the looping test model makes nine tool-request turns across three tool-using analysts. Their reports and the final rating are still produced. |
| [`test_graph_end_to_end.py`](../../test/offline/test_graph_end_to_end.py), `test_the_last_turn_is_offered_no_tools_and_reads_its_tool_results_as_text` | The forced wrap-up turn receives prior tool results as text and has no tools available. |

## Files changed

- `src/tradingagents/default_config.py` — `PROFILE_MAPPING`, `PROFILE_NAMES`, `_PROFILE_KEYS`, `ResolvedProfile`, `resolve_profile`, `_resolved_from_defaults`.
- `src/tradingagents/graph/trading_graph.py` — `profile`/`explicit_overrides` params, `_resolve_run_profile`, resolved wiring, `run_settings` profile block, `_run_signature`.
- `src/tradingagents/reporting.py`, `src/tradingagents/report_html.py` — report metadata (requested/overrides/resolved + tool cap).
- `src/cli/main.py`, `src/cli/run.py`, `src/cli/selections.py` — `--profile`, validation order, question skipping, effective-config display, base analysts.
- `test/offline/test_profiles.py`, `test_profiles_graph.py`, `test_profiles_report.py`, `test_cli_profile.py`, `test_cli_profile_e2e.py` — 71 FR-001 tests (new).
- Minimal adaptations to three existing CLI fakes (`test_cli_commands.py`, `test_cli_memory_log.py`, `test_rating_integrity.py`) for the new `profile`/`run_settings` wiring.
