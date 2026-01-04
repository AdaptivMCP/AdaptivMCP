from __future__ import annotations

import asyncio

import main
from github_mcp.main_tools import graphql_dashboard


def test_list_open_issues_graphql_maps_fields(monkeypatch):
    fake_response = {
        "data": {
            "repository": {
                "issues": {
                    "totalCount": 1,
                    "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                    "nodes": [
                        {
                            "id": "NODE1",
                            "databaseId": 101,
                            "number": 12,
                            "title": "Example issue",
                            "state": "OPEN",
                            "url": "https://github.com/octo/repo/issues/12",
                            "createdAt": "2024-01-01T00:00:00Z",
                            "updatedAt": "2024-01-02T00:00:00Z",
                            "closedAt": None,
                            "body": "Body text",
                            "author": {
                                "login": "octo",
                                "url": "https://github.com/octo",
                                "avatarUrl": "https://avatars.example.com/u/1",
                            },
                            "labels": {
                                "nodes": [
                                    {
                                        "name": "bug",
                                        "color": "f00",
                                        "description": "Bug label",
                                    }
                                ]
                            },
                            "assignees": {
                                "nodes": [
                                    {
                                        "login": "helper",
                                        "url": "https://github.com/helper",
                                        "avatarUrl": "https://avatars.example.com/u/2",
                                    }
                                ]
                            },
                            "comments": {"totalCount": 2},
                            "milestone": {
                                "title": "v1",
                                "state": "OPEN",
                                "url": "https://github.com/octo/repo/milestone/1",
                                "description": "Milestone",
                                "dueOn": "2024-02-01T00:00:00Z",
                                "createdAt": "2024-01-01T00:00:00Z",
                            },
                        }
                    ],
                }
            }
        }
    }

    async def fake_graphql_query(query: str, variables=None):
        assert "issues" in query
        assert variables == {
            "owner": "octo",
            "name": "repo",
            "first": 5,
            "after": "cursor-in",
            "states": ["OPEN"],
        }
        return fake_response

    monkeypatch.setattr(main, "graphql_query", fake_graphql_query)

    result = asyncio.run(
        graphql_dashboard.list_open_issues_graphql(
            "octo/repo",
            per_page=5,
            cursor="cursor-in",
        )
    )

    assert result["total_count"] == 1
    assert result["page_info"]["has_next_page"] is True
    assert result["page_info"]["end_cursor"] == "cursor-1"

    issue = result["issues"][0]
    assert issue["id"] == 101
    assert issue["node_id"] == "NODE1"
    assert issue["number"] == 12
    assert issue["state"] == "open"
    assert issue["html_url"] == "https://github.com/octo/repo/issues/12"
    assert issue["labels"][0]["name"] == "bug"
    assert issue["assignees"][0]["login"] == "helper"
    assert issue["comments"] == 2
    assert issue["milestone"]["title"] == "v1"


def test_list_recent_failures_graphql_filters(monkeypatch):
    fake_response = {
        "data": {
            "repository": {
                "workflowRuns": {
                    "totalCount": 3,
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {
                            "id": "RUN1",
                            "databaseId": 1,
                            "url": "https://github.com/octo/repo/actions/runs/1",
                            "name": "CI",
                            "event": "push",
                            "status": "COMPLETED",
                            "conclusion": "SUCCESS",
                            "createdAt": "2024-01-01T00:00:00Z",
                            "updatedAt": "2024-01-01T01:00:00Z",
                            "headBranch": "main",
                            "headSha": "abc",
                            "workflow": {"name": "CI"},
                        },
                        {
                            "id": "RUN2",
                            "databaseId": 2,
                            "url": "https://github.com/octo/repo/actions/runs/2",
                            "name": "CI",
                            "event": "push",
                            "status": "COMPLETED",
                            "conclusion": "FAILURE",
                            "createdAt": "2024-01-02T00:00:00Z",
                            "updatedAt": "2024-01-02T01:00:00Z",
                            "headBranch": "main",
                            "headSha": "def",
                            "workflow": {"name": "CI"},
                        },
                        {
                            "id": "RUN3",
                            "databaseId": 3,
                            "url": "https://github.com/octo/repo/actions/runs/3",
                            "name": "CI",
                            "event": "push",
                            "status": "COMPLETED",
                            "conclusion": "CANCELLED",
                            "createdAt": "2024-01-03T00:00:00Z",
                            "updatedAt": "2024-01-03T01:00:00Z",
                            "headBranch": "dev",
                            "headSha": "ghi",
                            "workflow": {"name": "CI"},
                        },
                    ],
                }
            }
        }
    }

    async def fake_graphql_query(query: str, variables=None):
        assert "workflowRuns" in query
        return fake_response

    monkeypatch.setattr(main, "graphql_query", fake_graphql_query)

    result = asyncio.run(
        graphql_dashboard.list_recent_failures_graphql(
            "octo/repo",
            branch="main",
            limit=5,
        )
    )

    assert result["limit"] == 5
    assert result["branch"] == "main"
    assert [run["id"] for run in result["runs"]] == [2]
    assert result["runs"][0]["conclusion"] == "failure"


def test_get_repo_dashboard_graphql_compacts(monkeypatch):
    fake_response = {
        "data": {
            "repository": {
                "nameWithOwner": "octo/repo",
                "description": "Demo",
                "url": "https://github.com/octo/repo",
                "isPrivate": False,
                "isArchived": False,
                "stargazerCount": 5,
                "forkCount": 1,
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-02T00:00:00Z",
                "owner": {"login": "octo", "url": "https://github.com/octo"},
                "defaultBranchRef": {"name": "main"},
                "pullRequests": {
                    "nodes": [
                        {
                            "id": "PR1",
                            "databaseId": 11,
                            "number": 11,
                            "title": "Add feature",
                            "state": "OPEN",
                            "url": "https://github.com/octo/repo/pull/11",
                            "createdAt": "2024-01-01T00:00:00Z",
                            "updatedAt": "2024-01-02T00:00:00Z",
                            "isDraft": False,
                            "author": {
                                "login": "dev",
                                "url": "https://github.com/dev",
                                "avatarUrl": "https://avatars.example.com/u/3",
                            },
                            "headRefName": "feature",
                            "baseRefName": "main",
                            "headRepository": {"nameWithOwner": "octo/repo"},
                            "baseRepository": {"nameWithOwner": "octo/repo"},
                        }
                    ]
                },
                "issues": {
                    "nodes": [
                        {
                            "id": "ISS1",
                            "databaseId": 21,
                            "number": 21,
                            "title": "Bug",
                            "state": "OPEN",
                            "url": "https://github.com/octo/repo/issues/21",
                            "createdAt": "2024-01-01T00:00:00Z",
                            "updatedAt": "2024-01-02T00:00:00Z",
                            "closedAt": None,
                            "author": {
                                "login": "reporter",
                                "url": "https://github.com/reporter",
                                "avatarUrl": "https://avatars.example.com/u/4",
                            },
                            "labels": {"nodes": []},
                            "assignees": {"nodes": []},
                            "comments": {"totalCount": 0},
                        }
                    ]
                },
                "workflowRuns": {
                    "nodes": [
                        {
                            "id": "RUN1",
                            "databaseId": 31,
                            "url": "https://github.com/octo/repo/actions/runs/31",
                            "name": "CI",
                            "event": "push",
                            "status": "COMPLETED",
                            "conclusion": "SUCCESS",
                            "createdAt": "2024-01-02T00:00:00Z",
                            "updatedAt": "2024-01-02T01:00:00Z",
                            "headBranch": "main",
                            "headSha": "abc",
                            "workflow": {"name": "CI"},
                        },
                        {
                            "id": "RUN2",
                            "databaseId": 32,
                            "url": "https://github.com/octo/repo/actions/runs/32",
                            "name": "CI",
                            "event": "push",
                            "status": "COMPLETED",
                            "conclusion": "FAILURE",
                            "createdAt": "2024-01-03T00:00:00Z",
                            "updatedAt": "2024-01-03T01:00:00Z",
                            "headBranch": "dev",
                            "headSha": "def",
                            "workflow": {"name": "CI"},
                        },
                    ]
                },
                "object": {
                    "entries": [
                        {
                            "name": "README.md",
                            "type": "blob",
                            "object": {"byteSize": 123},
                        },
                        {
                            "name": "src",
                            "type": "tree",
                            "object": {},
                        },
                    ]
                },
            }
        }
    }

    async def fake_graphql_query(query: str, variables=None):
        assert "repository" in query
        return fake_response

    monkeypatch.setattr(main, "graphql_query", fake_graphql_query)

    result = asyncio.run(graphql_dashboard.get_repo_dashboard_graphql("octo/repo"))

    assert result["branch"] == "main"
    assert result["repo"]["full_name"] == "octo/repo"
    assert result["pull_requests"][0]["number"] == 11
    assert result["issues"][0]["number"] == 21
    assert [run["id"] for run in result["workflows"]] == [31]
    assert {entry["path"] for entry in result["top_level_tree"]} == {
        "README.md",
        "src",
    }
