from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from scheduling.engine import (ALGORITHM, ALGORITHM_VERSION, CONFIG_VERSION, SHANGHAI,
                               ScheduleStateError, calculate, initial_card, make_scheduler,
                               scheduler_config, validate_card_state, validate_metadata)

NOW = datetime(2026, 10, 3, 15, 50, tzinfo=timezone.utc)


class PinnedFSRSEngineTests(SimpleTestCase):
    def setUp(self):
        self.initial = initial_card(101, NOW)

    def test_version_and_daily_configuration_are_pinned(self):
        scheduler = make_scheduler()
        self.assertEqual(ALGORITHM_VERSION, '6.3.2')
        self.assertEqual(len(scheduler.parameters), 21)
        self.assertEqual(scheduler.desired_retention, 0.9)
        self.assertEqual(scheduler.learning_steps, ())
        self.assertEqual(scheduler.relearning_steps, ())
        self.assertFalse(scheduler.enable_fuzzing)

    def test_cold_start_all_three_ratings_have_future_due(self):
        for rating in ('again', 'hard', 'good'):
            with self.subTest(rating=rating):
                result = calculate(self.initial, 101, rating, NOW)
                self.assertGreater(result.due_utc, NOW)
                self.assertGreater(result.due_date, NOW.astimezone(SHANGHAI).date())
                self.assertEqual(result.after_state['state'], 2)
                self.assertEqual(result.review_log['card_id'], 101)
                self.assertEqual(result.review_log['rating'], {'again': 1, 'hard': 2, 'good': 3}[rating])
        # Good is an ordinary successful review, never an instruction to stop reviewing.
        self.assertIsNotNone(calculate(self.initial, 101, 'good', NOW).due_utc)

    def test_same_inputs_have_no_fuzz_and_do_not_mutate_input(self):
        original = deepcopy(self.initial)
        first = calculate(self.initial, 101, 'hard', NOW)
        second = calculate(self.initial, 101, 'hard', NOW)
        self.assertEqual(first, second)
        self.assertEqual(self.initial, original)

    def test_first_intervals_match_the_pinned_defaults(self):
        intervals = {rating: (calculate(self.initial, 101, rating, NOW).due_utc - NOW).days
                     for rating in ('again', 'hard', 'good')}
        self.assertEqual(intervals, {'again': 1, 'hard': 1, 'good': 2})

    def test_json_round_trip_preserves_state(self):
        result = calculate(self.initial, 101, 'good', NOW)
        decoded = json.loads(json.dumps(result.after_state, allow_nan=False))
        self.assertEqual(validate_card_state(decoded, 101), result.after_state)
        next_result = calculate(decoded, 101, 'hard', NOW + timedelta(days=4))
        self.assertGreater(next_result.due_utc, NOW + timedelta(days=4))

    def test_same_day_and_overdue_reviews_remain_finite_future_schedules(self):
        first = calculate(self.initial, 101, 'good', NOW)
        for offset in (timedelta(seconds=20), timedelta(days=30)):
            for rating in ('again', 'hard', 'good'):
                with self.subTest(offset=offset, rating=rating):
                    result = calculate(first.after_state, 101, rating, NOW + offset)
                    self.assertGreater(result.due_utc, NOW + offset)
                    self.assertGreater(result.due_date, (NOW + offset).astimezone(SHANGHAI).date())

    def test_utc_and_shanghai_cross_day_are_explicit(self):
        just_before = datetime(2026, 10, 3, 15, 59, 59, tzinfo=timezone.utc)
        just_after = just_before + timedelta(seconds=1)
        before = calculate(initial_card(101, just_before), 101, 'again', just_before)
        after = calculate(initial_card(101, just_after), 101, 'again', just_after)
        self.assertEqual(before.due_date.isoformat(), '2026-10-04')
        self.assertEqual(after.due_date.isoformat(), '2026-10-05')
        self.assertEqual(after.due_utc.tzinfo, timezone.utc)

    def test_non_utc_aware_review_time_is_normalized(self):
        result = calculate(self.initial, 101, 'hard', NOW.astimezone(SHANGHAI))
        self.assertEqual(result.reviewed_at, NOW)

    def test_naive_or_reversed_times_are_rejected(self):
        with self.assertRaises(ValidationError):
            calculate(self.initial, 101, 'good', NOW.replace(tzinfo=None))
        first = calculate(self.initial, 101, 'good', NOW)
        with self.assertRaises(ValidationError):
            calculate(first.after_state, 101, 'good', NOW - timedelta(seconds=1))

    def test_invalid_or_easy_rating_is_not_silently_mapped(self):
        for rating in ('easy', 1, None, '', 'GOOD'):
            with self.subTest(rating=rating), self.assertRaises(ValidationError):
                calculate(self.initial, 101, rating, NOW)

    def test_invalid_card_shapes_and_id_types_are_rejected(self):
        cases = [None, [], {}, {**self.initial, 'extra': 1},
                 {**self.initial, 'card_id': True}, {**self.initial, 'card_id': '101'},
                 {**self.initial, 'card_id': 0}, {**self.initial, 'card_id': 102},
                 {**self.initial, 'state': True}, {**self.initial, 'state': 3},
                 {**self.initial, 'step': True}, {**self.initial, 'step': -1}]
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(ScheduleStateError):
                validate_card_state(payload, 101)

    def test_invalid_memory_numbers_are_rejected_without_coercion(self):
        valid = calculate(self.initial, 101, 'good', NOW).after_state
        cases = [('stability', value) for value in (None, 0, -1, True, '2', float('nan'), float('inf'))]
        cases += [('difficulty', value) for value in (None, 0, 11, True, '2', float('nan'))]
        for field, value in cases:
            with self.subTest(field=field, value=value), self.assertRaises(ScheduleStateError):
                validate_card_state({**valid, field: value}, 101)

    def test_naive_non_utc_and_impossible_state_dates_are_rejected(self):
        valid = calculate(self.initial, 101, 'good', NOW).after_state
        cases = [
            {**valid, 'due': NOW.replace(tzinfo=None).isoformat()},
            {**valid, 'due': NOW.astimezone(SHANGHAI).isoformat()},
            {**valid, 'due': NOW.isoformat()},
            {**valid, 'last_review': None},
            {**valid, 'last_review': 'not a date'},
            {**self.initial, 'difficulty': 3},
        ]
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(ScheduleStateError):
                validate_card_state(payload, 101)

    def test_unsupported_algorithm_or_modified_config_is_explicit_error(self):
        original = scheduler_config()
        validate_metadata(ALGORITHM, ALGORITHM_VERSION, CONFIG_VERSION, original)
        for arguments in [('sm2', ALGORITHM_VERSION, CONFIG_VERSION, original),
                          (ALGORITHM, '5', CONFIG_VERSION, original),
                          (ALGORITHM, ALGORITHM_VERSION, 'other', original),
                          (ALGORITHM, ALGORITHM_VERSION, CONFIG_VERSION,
                           {**original, 'enable_fuzzing': 0}),
                          (ALGORITHM, ALGORITHM_VERSION, CONFIG_VERSION,
                           {**original, 'desired_retention': 0.85})]:
            with self.subTest(arguments=arguments), self.assertRaises(ScheduleStateError):
                validate_metadata(*arguments)

    def test_wrong_installed_version_is_explicit_error(self):
        with patch('scheduling.engine.version', return_value='7.0.0'):
            with self.assertRaises(ScheduleStateError):
                make_scheduler()
