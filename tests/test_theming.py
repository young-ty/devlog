"""模块 3 测试：主题聚类、里程碑与静默期识别。"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from devlog.core.git_source.models import CommitEvent, NoiseType
from devlog.core.theming.cluster import cluster_themes


TZ = timezone(timedelta(hours=8))


def at(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 9, day, hour, 0, tzinfo=TZ)


def make_event(
    number: int,
    day: int,
    subject: str,
    noise: NoiseType = NoiseType.NONE,
) -> CommitEvent:
    return CommitEvent(
        hash=f"{number:040d}",
        short_hash=f"{number:07d}",
        author_name="dev",
        author_email="dev@example.com",
        committed_at=at(day),
        message_subject=subject,
        files_changed=1,
        insertions=1,
        deletions=0,
        parents_count=0,
        noise_type=noise,
    )


class ThemeClusteringTests(unittest.TestCase):
    def test_related_keywords_form_single_theme(self) -> None:
        events = [
            make_event(1, 1, "feat: add login page"),
            make_event(2, 2, "fix: fix login button"),
            make_event(3, 3, "feat: polish login flow"),
        ]

        result = cluster_themes(events)

        self.assertEqual(len(result.themes), 1)
        theme = result.themes[0]
        self.assertEqual(theme.title, "login")
        self.assertEqual(theme.commit_count, 3)
        self.assertEqual(len(theme.commit_hashes), 3)
        self.assertEqual(theme.kind, "feature")

    def test_unrelated_keywords_form_separate_themes(self) -> None:
        events = [
            make_event(1, 1, "feat: add login page"),
            make_event(2, 2, "feat: add payment page"),
        ]

        result = cluster_themes(events)

        self.assertEqual(len(result.themes), 2)
        self.assertEqual([theme.title for theme in result.themes], ["login", "payment"])

    def test_chinese_commits_cluster_by_shared_topic(self) -> None:
        """中文提交没有空格，必须靠 2 字滑窗词元才能聚到一起。"""

        events = [
            make_event(1, 1, "feat: 新增菜谱推荐接口"),
            make_event(2, 2, "fix: 菜谱推荐结果去重"),
            make_event(3, 3, "feat: 推荐接口加上分页"),
        ]

        result = cluster_themes(events)

        self.assertEqual(len(result.themes), 1)
        self.assertEqual(result.themes[0].commit_count, 3)
        # 中文主题标题用可读原句，而不是 bigram 碎片。
        self.assertEqual(result.themes[0].title, "新增菜谱推荐接口")

    def test_chinese_action_words_do_not_merge_unrelated_work(self) -> None:
        """两条提交都写了"新增"不代表它们是同一件事。"""

        events = [
            make_event(1, 1, "feat: 新增菜谱推荐接口"),
            make_event(2, 2, "feat: 新增登录页面"),
        ]

        result = cluster_themes(events)

        self.assertEqual(len(result.themes), 2)

    def test_mixed_chinese_and_english_subjects_cluster(self) -> None:
        events = [
            make_event(1, 1, "feat: 新增 login 登录页面"),
            make_event(2, 2, "fix: login 按钮错位"),
        ]

        result = cluster_themes(events)

        self.assertEqual(len(result.themes), 1)

    def test_noise_commits_do_not_split_or_enter_themes(self) -> None:
        events = [
            make_event(1, 1, "feat: add login page"),
            make_event(2, 1, "wip: half finished", NoiseType.WIP),
            make_event(3, 2, "Merge branch 'x'", NoiseType.MERGE),
            make_event(4, 3, "fix: fix login button"),
        ]

        result = cluster_themes(events)

        self.assertEqual(len(result.themes), 1)
        self.assertEqual(result.themes[0].commit_count, 2)
        self.assertEqual(
            result.themes[0].commit_hashes,
            (f"{1:040d}", f"{4:040d}"),
        )

    def test_milestone_candidate_detected(self) -> None:
        events = [
            make_event(1, 1, "feat: add login page"),
            make_event(2, 2, "release: v1.0"),
        ]

        result = cluster_themes(events)

        self.assertEqual(len(result.themes), 2)
        self.assertFalse(result.themes[0].is_milestone_candidate)
        self.assertTrue(result.themes[1].is_milestone_candidate)
        self.assertEqual(result.themes[1].title, "release: v1.0")

    def test_silence_period_over_threshold(self) -> None:
        events = [
            make_event(1, 1, "feat: add login page"),
            make_event(2, 5, "feat: add payment page"),
        ]

        result = cluster_themes(events)

        self.assertEqual(len(result.silence_periods), 1)
        silence = result.silence_periods[0]
        self.assertEqual(silence.days, 4)
        self.assertEqual(silence.started_at, at(1))
        self.assertEqual(silence.ended_at, at(5))

    def test_short_gap_is_not_a_silence_period(self) -> None:
        events = [
            make_event(1, 1, "feat: add login page"),
            make_event(2, 2, "feat: add payment page"),
        ]

        result = cluster_themes(events)

        self.assertEqual(result.silence_periods, [])

    def test_empty_and_all_noise_inputs(self) -> None:
        empty = cluster_themes([])
        self.assertEqual(empty.themes, [])
        self.assertEqual(empty.silence_periods, [])

        all_noise = cluster_themes(
            [
                make_event(1, 1, "wip: x", NoiseType.WIP),
                make_event(2, 1, "chore: y", NoiseType.CHORE),
            ]
        )
        self.assertEqual(all_noise.themes, [])
        self.assertEqual(all_noise.silence_periods, [])

    def test_clustering_is_deterministic(self) -> None:
        events = [
            make_event(1, 1, "feat: add login page"),
            make_event(2, 2, "fix: fix login button"),
            make_event(3, 3, "feat: add payment page"),
        ]

        first = cluster_themes(events)
        second = cluster_themes(events)

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
