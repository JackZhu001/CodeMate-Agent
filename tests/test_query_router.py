from codemate_agent.retrieval import QueryRouter


def test_query_router_routes_symbol_lookup():
    router = QueryRouter()

    plan = router.route("publish_skill_draft 在哪")

    assert plan.mode == "symbol_lookup"
    assert plan.use_repo_map is False
    assert plan.use_lexical is True


def test_query_router_routes_scope_exploration():
    router = QueryRouter()

    plan = router.route("skill 自动沉淀这个功能涉及哪些模块，应该看哪几层实现")

    assert plan.mode == "scope_exploration"
    assert plan.use_repo_map is True
    assert plan.use_localization is True


def test_query_router_routes_concept_lookup():
    router = QueryRouter()

    plan = router.route("团队阶段顺序怎么保证")

    assert plan.mode == "concept_lookup"
    assert plan.use_repo_map is True
    assert plan.use_lexical is True
