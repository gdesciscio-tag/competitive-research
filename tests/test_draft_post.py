# tests/test_draft_post.py
from compresearch.draft_post import select_topic
from compresearch.models import TopicalMap, PillarTopic, TopicCluster, ArticleIdea


def _map():
    return TopicalMap(pillars=[PillarTopic(name="P", clusters=[TopicCluster(name="C", articles=[
        ArticleIdea(title="Low one", target_keyword="low", estimated_volume=100),
        ArticleIdea(title="High one", target_keyword="high", estimated_volume=900),
        ArticleIdea(title="Unknown vol", target_keyword="unknown"),
    ])])])


def test_select_topic_picks_highest_volume():
    assert select_topic(_map()).target_keyword == "high"


def test_select_topic_honors_preferred_keyword():
    assert select_topic(_map(), preferred_keyword="low").target_keyword == "low"


def test_select_topic_none_when_empty():
    assert select_topic(None) is None
    assert select_topic(TopicalMap(pillars=[])) is None
