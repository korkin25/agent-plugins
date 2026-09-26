"""Claude purpose and effort metadata from isolated native initialize; fake binary only."""
import copy
import json
import os
from pathlib import Path
import time
from unittest import mock

from test_router import Sandbox, router, CLAUDE_MODELS, agent_input
import router_claude_catalog as catalog


class NativeClaudeCatalogTests(Sandbox):
    def calls(self):
        path = self.claude_state / "calls.log"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def fetch(self, **kwargs):
        return catalog.fetch_catalog(str(self.fake_claude), **kwargs)

    def test_fetch_only_initializes_and_discards_account_data(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "SYNTHETIC_KEY_NOT_FORWARD",
                                          "ANTHROPIC_DEFAULT_SONNET_MODEL": "SYNTHETIC_OVERRIDE_NOT_FORWARD"}):
            result = self.fetch()
        self.assertEqual(result, self.native_claude_catalog)
        [call] = self.calls()
        self.assertEqual(call["request"], {"type": "control_request", "request_id": catalog.REQUEST_ID,
                                          "request": {"subtype": "initialize"}})
        self.assertIn("--bare", call["argv"])
        self.assertIn("--no-session-persistence", call["argv"])
        self.assertEqual(call["argv"][call["argv"].index("--setting-sources") + 1], "")
        self.assertEqual(call["argv"][call["argv"].index("--mcp-config") + 1], '{"mcpServers":{}}')
        self.assertEqual(call["config_mode"], 0o700)
        self.assertEqual(call["cwd"], call["home"])
        self.assertTrue(call["cwd"].startswith('/var/tmp/smr-claude-catalog-'))
        self.assertFalse(Path(call["cwd"]).exists())
        self.assertNotIn('ANTHROPIC_API_KEY', call['environment_keys'])
        self.assertNotIn('ANTHROPIC_DEFAULT_SONNET_MODEL', call['environment_keys'])
        self.assertFalse((self.claude_state / 'unexpected-input').exists())
        self.assertNotIn('SYNTHETIC_ACCOUNT', json.dumps(result))
        self.assertNotIn('SYNTHETIC_COMMAND', json.dumps(result))
        self.assertFalse(Path(f"/proc/{call['pid']}").exists())

    def test_timeout_is_bounded_and_native_process_is_reaped(self):
        (self.claude_state / 'mode').write_text('sleep')
        started = time.monotonic()
        self.assertIsNone(self.fetch(timeout=.15))
        self.assertLess(time.monotonic() - started, 1.5)
        [call] = self.calls()
        self.assertFalse(Path(f"/proc/{call['pid']}").exists())
        self.assertFalse(Path(call['cwd']).exists())

    def test_malformed_error_wrong_request_and_oversized_responses_fail_closed(self):
        for mode in ('garbage', 'error', 'wrong_id', 'huge'):
            with self.subTest(mode=mode):
                (self.claude_state / 'mode').write_text(mode)
                self.assertIsNone(self.fetch(timeout=.2))
                self.assertFalse(Path(f"/proc/{self.calls()[-1]['pid']}").exists())

    def test_alias_mapping_canonical_alias_precedes_variant(self):
        models = copy.deepcopy(CLAUDE_MODELS)
        models.append(dict(models[1], value='claude-sonnet-old', description='Older alternate description'))
        parsed = catalog.parse_models(models)
        self.assertEqual(set(parsed), {'haiku', 'sonnet', 'opus', 'fable'})
        self.assertEqual(parsed['sonnet']['catalog_value'], 'sonnet')
        self.assertEqual(parsed['opus']['catalog_value'], 'opus[1m]')
        self.assertEqual(parsed['fable']['catalog_value'], 'claude-fable-5-1')
        self.assertEqual(parsed['sonnet']['supported_efforts'], ['low', 'medium', 'high', 'xhigh', 'max'])
        self.assertFalse(parsed['haiku']['supports_effort'])

    def test_ambiguous_variants_or_conflicting_exact_aliases_are_excluded(self):
        variants = [dict(CLAUDE_MODELS[2], value='opus[1m]'),
                    dict(CLAUDE_MODELS[2], value='claude-opus-other', description='Different purpose')]
        self.assertFalse(catalog.parse_models(variants))
        exact = [dict(CLAUDE_MODELS[1]), dict(CLAUDE_MODELS[1], description='Conflicting purpose')]
        self.assertFalse(catalog.parse_models(exact))
        self.assertIsNotNone(catalog.parse_models([CLAUDE_MODELS[1], CLAUDE_MODELS[1]]))

    def test_unknown_inherited_variants_and_missing_purpose_are_excluded(self):
        for value in ('default', 'inherit', 'sonnet[unknown]', 'haiku[1m]', 'custom', 'claude-newfamily-1'):
            self.assertIsNone(catalog.parse_models([dict(CLAUDE_MODELS[1], value=value)]))
        for description in (None, '', '   ', 123):
            parsed = catalog.parse_models([dict(CLAUDE_MODELS[1], description=description)])
            self.assertFalse(parsed)
            self.assertEqual(parsed.missing_descriptions, ['claude-sonnet-5'])

    def test_native_effort_capability_has_no_static_model_assumptions(self):
        unknown = dict(CLAUDE_MODELS[1], supportedEffortLevels=[])
        self.assertFalse(catalog.parse_models([unknown]))
        unknown.pop('supportedEffortLevels')
        self.assertFalse(catalog.parse_models([unknown]))
        self.assertFalse(catalog.parse_models([dict(CLAUDE_MODELS[1], supportedEffortLevels=['invented'])]))
        unsupported_fable = dict(CLAUDE_MODELS[-1], supportsEffort=False, supportedEffortLevels=[])
        parsed = catalog.parse_models([unsupported_fable])
        with mock.patch.object(router, 'claude_catalog', return_value=(parsed, None)):
            options = router.selection_options(router.normalize_config({}), 'claude')
        self.assertEqual([(v['model'], v['effort']) for v in options.values()], [('fable', None)])

    def test_candidate_criteria_use_native_purpose_and_official_effort(self):
        options = router.selection_options(router.normalize_config({}), 'claude')
        self.assertEqual(len(options), 16)
        criteria = router.selection_questions(options, 'claude')['selection']
        self.assertIn('do not assume capabilities from a name or prior training', criteria['instructions'])
        for key, value in options.items():
            self.assertIn(self.native_claude_catalog[value['model']]['description'], criteria['instructions'])
            if value['effort']:
                self.assertIn(catalog.EFFORT_DESCRIPTIONS[value['effort']], criteria['criteria'][key])
                self.assertIn(catalog.EFFORT_SOURCE, criteria['instructions'])
            self.assertNotEqual(value['model'], value['model_catalog_resolved_id'])

    def test_allowlists_intersect_current_native_support_without_invented_levels(self):
        cfg = router.normalize_config({'claude': {'allowed_models': ['fable'], 'efforts': ['xhigh']}})
        options = router.selection_options(cfg, 'claude')
        self.assertEqual([(v['model'], v['effort']) for v in options.values()], [('fable', 'xhigh')])
        missing_effort = copy.deepcopy(self.native_claude_catalog)
        missing_effort['fable']['supported_efforts'] = ['low']
        with mock.patch.object(router, 'claude_catalog', return_value=(missing_effort, None)), self.assertRaises(router.JevError):
            router.selection_options(cfg, 'claude')

    def test_cache_identity_and_sanitized_fields(self):
        with mock.patch.dict(os.environ, self.env(), clear=True):
            loaded, _ = catalog.load_cached_catalog(str(self.fake_claude))
            self.assertEqual(loaded, self.native_claude_catalog)
            other = self.fake_claude.with_name('other-claude')
            other.write_bytes(self.fake_claude.read_bytes())
            other.chmod(0o755)
            self.assertEqual(catalog.load_cached_catalog(str(other)), (None, None))
            info = self.fake_claude.stat()
            os.utime(self.fake_claude, ns=(info.st_atime_ns, info.st_mtime_ns + 1000))
            self.assertEqual(catalog.load_cached_catalog(str(self.fake_claude)), (None, None))
        self.assertEqual(self.claude_cache.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('account', self.claude_cache.read_text())

    def test_cache_rejects_foreign_metadata_fields(self):
        data = json.loads(self.claude_cache.read_text())
        next(iter(data['binaries'].values()))['models']['sonnet']['account'] = 'never-use'
        self.claude_cache.write_text(json.dumps(data))
        with mock.patch.dict(os.environ, self.env(), clear=True):
            self.assertEqual(catalog.load_cached_catalog(str(self.fake_claude)), (None, None))

    def test_hook_warm_cache_never_initializes_native_client(self):
        self.serve()
        self.write_config()
        self.assertEqual(self.routed_model(self.hook()[1]), 'haiku')
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.last_row()['model_catalog_source'], 'isolated_claude_sdk_initialize')
        self.assertEqual(self.last_row()['model'], 'haiku')
        self.assertEqual(self.last_row()['model_catalog_resolved_id'], 'claude-haiku-4-5')

    def test_missing_catalog_skips_jev_and_refreshes_in_background(self):
        self.serve()
        self.write_config()
        self.claude_cache.unlink()
        self.assertEqual(self.hook()[:3], (0, '', ''))
        self.assertFalse(self.last_row()['jev_attempted'])
        self.assertEqual(self.last_row()['reason'], 'error:no_catalog;refreshing')
        self.assertEqual(self.fake.requests, [])
        self.assertTrue(self.wait_until(self.claude_cache.exists, timeout=5))
        self.assertEqual(self.routed_model(self.hook()[1]), 'haiku')
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.wait_background(), [])

    def test_check_refreshes_native_metadata_synchronously_without_model_turn(self):
        self.write_config()
        self.claude_cache.unlink()
        rc, out, err, _ = self.run_router('check')
        self.assertEqual((rc, err), (0, ''))
        self.assertIn('Claude model catalog: 4 models', out)
        self.assertIn('Synthetic Fable: hardest and long-running tasks', out)
        self.assertTrue(self.claude_cache.exists())
        self.assertEqual(len(self.calls()), 1)
        self.assertFalse((self.claude_state / 'unexpected-input').exists())

    def test_model_alias_overrides_skip_before_paid_jev(self):
        self.serve()
        self.write_config()
        for name in ('ANTHROPIC_DEFAULT_HAIKU_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL',
                     'ANTHROPIC_DEFAULT_OPUS_MODEL', 'ANTHROPIC_DEFAULT_FABLE_MODEL'):
            self.assertEqual(self.hook(env=self.env(**{name: 'custom-model'}))[:3], (0, '', ''))
            self.assertEqual(self.last_row()['reason'], 'override')
            self.assertEqual(self.last_row()['override_source'], 'model_catalog')
            self.assertFalse(self.last_row()['jev_attempted'])
        self.assertEqual(self.fake.requests, [])
        self.assertEqual(self.calls(), [])

    def test_binary_detection_prefers_actual_ancestor_then_config_then_absolute_path(self):
        with mock.patch.object(router, 'parent_claude', return_value='/actual/native/claude'):
            self.assertEqual(router.find_claude(str(self.fake_claude)), ('/actual/native/claude', 'parent process'))
        with mock.patch.object(router, 'parent_claude', return_value=None):
            self.assertEqual(router.find_claude(str(self.fake_claude), path=''), (str(self.fake_claude), 'claude_bin'))
            self.assertEqual(router.find_claude(path=str(self.fakebin)), (str(self.fake_claude), 'PATH'))
            self.assertEqual(router.find_claude(path='.:relative'), (None, None))

    def test_native_version_named_ancestor_is_evidenced_not_guessed(self):
        versioned = self.root / 'claude/versions/2.1.280'
        versioned.parent.mkdir(parents=True)
        versioned.write_text('#!/bin/sh\nexit 0\n')
        versioned.chmod(0o755)
        proc = self.root / 'proc/123'
        proc.mkdir(parents=True)
        (proc / 'exe').symlink_to(versioned)
        self.assertEqual(router.parent_claude(str(proc.parent), start_pid=123), str(versioned))


class PurposeAndPriceIntegrationTests(Sandbox):
    def test_same_identity_reuses_purpose_but_changed_resolved_model_does_not(self):
        row = dict(CLAUDE_MODELS[1], description='')
        same = catalog.parse_models([row], previous=self.native_claude_catalog)
        self.assertEqual(same['sonnet']['description'], self.native_claude_catalog['sonnet']['description'])
        changed = catalog.parse_models([dict(row, resolvedModel='claude-sonnet-next')], previous=self.native_claude_catalog)
        self.assertFalse(changed)
        self.assertEqual(changed.inventory, ['claude-sonnet-next'])
        self.assertEqual(changed.missing_descriptions, ['claude-sonnet-next'])

    def test_claude_purpose_cache_has_no_age_expiration(self):
        data = json.loads(self.claude_cache.read_text())
        next(iter(data['binaries'].values()))['ts'] = time.time() - 500 * 86400
        self.claude_cache.write_text(json.dumps(data))
        with mock.patch.dict(os.environ, self.env(), clear=True):
            cached, _ = catalog.load_cached_catalog(str(self.fake_claude))
        self.assertEqual(cached, self.native_claude_catalog)

    def test_shared_purpose_once_and_separate_official_or_unknown_prices(self):
        native = copy.deepcopy(self.native_claude_catalog)
        native['sonnet']['description'] = 'Native Sonnet purpose · $2/$10 per Mtok'
        record = {'status': 'stale', 'retrieved_at': 123, 'source_url': 'https://official.example/pricing',
                  'unit': 'USD/1M tokens', 'input': 3, 'output': 15, 'cached_input': .3, 'cache_write': None,
                  'conditions': 'Standard context; excludes batch pricing'}
        self.price_stub.cached_prices.return_value = {'claude-sonnet-5': record}
        cfg = router.normalize_config({'claude': {'allowed_models': ['sonnet']}})
        with mock.patch.object(router, 'claude_catalog', return_value=(native, None)):
            options = router.selection_options(cfg, 'claude')
        question = router.selection_questions(options, 'claude')['selection']
        serialized = json.dumps(question)
        self.assertEqual(serialized.count('Native Sonnet purpose'), 1)
        self.assertNotIn('$2/$10', serialized)
        self.assertEqual(serialized.count('Standard context; excludes batch pricing'), 1)
        self.assertIn('unknown is not free', serialized)
        for option in options.values():
            self.assertEqual(option['price_reference']['model_id'], 'claude-sonnet-5')
            self.assertEqual(option['price_reference']['basis'], 'standard_api')
            self.assertEqual(option['price_reference']['status'], 'stale')
        self.price_stub.ensure_prices.assert_called_once_with('claude', ['claude-sonnet-5'])
        self.price_stub.cached_prices.return_value = {}
        with mock.patch.object(router, 'claude_catalog', return_value=(native, None)):
            unknown = router.selection_options(cfg, 'claude')
        self.assertEqual(next(iter(unknown.values()))['price_reference']['status'], 'unknown')
        self.assertNotIn('$2/$10', json.dumps(router.selection_questions(unknown, 'claude')))

    def test_price_failure_does_not_discard_stale_verified_reference(self):
        self.price_stub.ensure_prices.side_effect = OSError('offline')
        self.price_stub.cached_prices.return_value = {'claude-opus-5-5': {'status': 'stale', 'input': 5, 'output': 25}}
        cfg = router.normalize_config({'claude': {'allowed_models': ['opus']}})
        options = router.selection_options(cfg, 'claude')
        self.assertTrue(options)
        self.assertEqual(next(iter(options.values()))['price_reference']['status'], 'stale')
        self.assertEqual(next(iter(options.values()))['price_reference']['input'], 5)

    def test_missing_allowlist_model_requests_refresh_before_skipping(self):
        cfg = router.normalize_config({'claude': {'allowed_models': ['fable']}})
        old = {key: value for key, value in self.native_claude_catalog.items() if key != 'fable'}
        with mock.patch.object(router, 'claude_catalog', return_value=(old, None)), \
                mock.patch.object(router, 'request_catalog_refresh') as refresh, self.assertRaises(router.JevError):
            router.selection_options(cfg, 'claude')
        refresh.assert_called_once_with(cfg, 'claude', requested_models=['fable'])

    def test_codex_source_stat_probe_refreshes_prices_only_for_inventory_change(self):
        from test_router import CATALOG
        cfg = router.normalize_config({'codex_bin': str(self.fake_codex)})
        native_dir = self.home / '.codex'
        native_dir.mkdir()
        snapshot = native_dir / 'models_cache.json'
        snapshot.write_text('OPAQUE NATIVE METADATA CONTENT MUST NOT BE READ')
        with mock.patch.dict(os.environ, self.env(), clear=True), \
                mock.patch.object(router, 'parent_codex', return_value=None), \
                mock.patch.object(router, 'start_refresh') as start:
            current, _ = router.codex_catalog(cfg)
            self.assertIsNotNone(current)
            start.assert_called_once()
            self.assertTrue(router.refresh_catalog(str(self.fake_codex)))
            self.price_stub.ensure_prices.assert_not_called()  # mtime alone is not a pricing event
            start.reset_mock()
            router.codex_catalog(cfg)
            start.assert_not_called()
            updated = copy.deepcopy(CATALOG)
            updated['models'].append({'slug': 'gpt-new-native', 'visibility': 'list', 'description': 'New native purpose',
                                      'supported_reasoning_levels': [{'effort': 'high', 'description': 'New native effort'}]})
            self.write_catalog(updated)
            stamp = snapshot.stat()
            os.utime(snapshot, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1000))
            self.assertTrue(router.refresh_catalog(str(self.fake_codex)))
            self.price_stub.ensure_prices.assert_called_once_with('codex', [m['slug'] for m in updated['models']], force=True)
            start.reset_mock()
            router.codex_catalog(cfg)
            start.assert_not_called()

    def test_claude_unchanged_startup_probe_reuses_purpose_without_price_refresh(self):
        with mock.patch.dict(os.environ, self.env(), clear=True):
            callback = mock.Mock()
            self.assertTrue(catalog.refresh_catalog(str(self.fake_claude), force=True, on_change=callback))
            callback.assert_not_called()
            changed = copy.deepcopy(CLAUDE_MODELS)
            changed[1]['resolvedModel'] = 'claude-sonnet-new'
            (self.claude_state / 'models.json').write_text(json.dumps(changed))
            self.assertTrue(catalog.refresh_catalog(str(self.fake_claude), force=True, on_change=callback))
            callback.assert_called_once()
            self.assertIn('claude-sonnet-new', callback.call_args.args[0].inventory)

    def test_repeated_missing_purpose_does_not_repeat_force_price_refresh(self):
        models = copy.deepcopy(CLAUDE_MODELS)
        models[1]['resolvedModel'] = 'claude-sonnet-future'
        models[1]['description'] = ''
        (self.claude_state / 'models.json').write_text(json.dumps(models))
        with mock.patch.dict(os.environ, self.env(), clear=True):
            callback = mock.Mock()
            self.assertTrue(catalog.refresh_catalog(str(self.fake_claude), force=True, on_change=callback))
            callback.assert_called_once()
            callback.reset_mock()
            self.assertTrue(catalog.refresh_catalog(str(self.fake_claude), force=True, on_change=callback))
            callback.assert_not_called()
            cached, _ = catalog.load_cached_catalog(str(self.fake_claude))
            self.assertIn('claude-sonnet-future', cached.inventory)
            self.assertIn('claude-sonnet-future', cached.missing_descriptions)
            self.assertNotIn('sonnet', cached)

    def test_codex_known_identity_can_keep_previously_verified_native_purpose(self):
        from test_router import CATALOG
        previous = router.parse_catalog(json.dumps(CATALOG).encode())
        current = copy.deepcopy(CATALOG)
        current['models'][0]['description'] = ''
        result = router.parse_catalog(json.dumps(current).encode(), previous)
        self.assertEqual(result.metadata['gpt-5.5']['description'], previous.metadata['gpt-5.5']['description'])
        self.assertEqual(result.missing_descriptions, [])
        current['models'][0]['slug'] = 'gpt-brand-new'
        result = router.parse_catalog(json.dumps(current).encode(), previous)
        self.assertNotIn('gpt-brand-new', result)
        self.assertIn('gpt-brand-new', result.inventory)
        self.assertIn('gpt-brand-new', result.missing_descriptions)

    def test_unchanged_known_missing_purpose_never_reprobes_on_launch(self):
        rows = copy.deepcopy(CLAUDE_MODELS)
        rows[1]['resolvedModel'] = 'claude-sonnet-unexplained'
        rows[1]['description'] = ''
        incomplete = catalog.parse_models(rows)
        with mock.patch.dict(os.environ, self.env(), clear=True):
            catalog.save_catalog(str(self.fake_claude), incomplete)
            with mock.patch.object(router, 'parent_claude', return_value=None), \
                    mock.patch.object(catalog, 'start_refresh') as start:
                # Exercise the real helper despite Sandbox's choice fixture.
                native_helper = self.claude_catalog_mock.temp_original
                for _ in range(2):
                    loaded, problem = native_helper(router.normalize_config({'claude_bin': str(self.fake_claude)}))
                    self.assertIsNone(problem)
                    self.assertEqual(loaded.missing_descriptions, ['claude-sonnet-unexplained'])
                start.assert_not_called()

    def test_unknown_allowlist_probe_marker_changes_only_with_requested_set_or_binary(self):
        with mock.patch.dict(os.environ, self.env(), clear=True):
            self.assertTrue(router.allowlist_probe_needed(str(self.fake_claude), 'claude', ['fable']))
            self.assertFalse(router.allowlist_probe_needed(str(self.fake_claude), 'claude', ['fable']))
            self.assertTrue(router.allowlist_probe_needed(str(self.fake_claude), 'claude', ['sonnet']))
            stamp = self.fake_claude.stat()
            os.utime(self.fake_claude, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1000))
            self.assertTrue(router.allowlist_probe_needed(str(self.fake_claude), 'claude', ['sonnet']))
        marker = self.cache.parent / 'catalog-allowlist-probes.json'
        self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('sonnet', marker.read_text())
        self.assertNotIn(str(self.fake_claude), marker.read_text())
