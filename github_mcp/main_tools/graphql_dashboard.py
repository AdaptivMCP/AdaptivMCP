from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple

from github_mcp.utils import _normalize_repo_path_for_repo

from ._main import _main

ISSUES_QUERY = """
query($owner: String!, $name: String!, $first: Int!, $after: String, $states: [IssueState!]) {
  repository(owner: $owner, name: $name) {
    issues(first: $first, after: $after, states: $states, orderBy: {field: UPDATED_AT, direction: DESC}) {
      totalCount
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        id
        databaseId
        number
        title
        state
        url
        createdAt
        updatedAt
        closedAt
        body
        author {
          login
          url
          avatarUrl
        }
        labels(first: 20) {
          nodes {
            name
            color
            description
          }
        }
        assignees(first: 20) {
          nodes {
            login
            url
            avatarUrl
          }
        }
        comments {
          totalCount
        }
        milestone {
          title
          state
          url
          description
          dueOn
          createdAt
        }
      }
    }
  }
}
"""

WORKFLOW_RUNS_QUERY = """
query($owner: String!, $name: String!, $first: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    workflowRuns(first: $first, after: $after, orderBy: {field: CREATED_AT, direction: DESC}) {
      totalCount
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        id
        databaseId
        url
        name
        event
        status
        conclusion
        createdAt
        updatedAt
        headBranch
        headSha
        workflow {
          name
        }
      }
    }
  }
}
"""

DASHBOARD_QUERY = """
query(
  $owner: String!,
  $name: String!,
  $issuesFirst: Int!,
  $pullsFirst: Int!,
  $runsFirst: Int!,
  $treeExpression: String!
) {
  repository(owner: $owner, name: $name) {
    nameWithOwner
    description
    url
    isPrivate
    isArchived
    stargazerCount
    forkCount
    createdAt
    updatedAt
    owner {
      login
      url
    }
    defaultBranchRef {
      name
    }
    pullRequests(first: $pullsFirst, states: OPEN, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {
        id
        databaseId
        number
        title
        state
        url
        createdAt
        updatedAt
        isDraft
        author {
          login
          url
          avatarUrl
        }
        headRefName
        baseRefName
        headRepository {
          nameWithOwner
        }
        baseRepository {
          nameWithOwner
        }
      }
    }
    issues(first: $issuesFirst, states: OPEN, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {
        id
        databaseId
        number
        title
        state
        url
        createdAt
        updatedAt
        closedAt
        author {
          login
          url
          avatarUrl
        }
        labels(first: 20) {
          nodes {
            name
            color
            description
          }
        }
        assignees(first: 20) {
          nodes {
            login
            url
            avatarUrl
          }
        }
        comments {
          totalCount
        }
      }
    }
    workflowRuns(first: $runsFirst, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes {
        id
        databaseId
        url
        name
        event
        status
        conclusion
        createdAt
        updatedAt
        headBranch
        headSha
        workflow {
          name
        }
      }
    }
    object(expression: $treeExpression) {
      ... on Tree {
        entries {
          name
          type
          object {
            ... on Blob {
              byteSize
            }
          }
        }
      }
    }
  }
}
"""


def _split_full_name(full_name: str) -> Tuple[str, str]:
    if "/" not in full_name:
        raise ValueError("full_name must be in owner/repo format")
    owner, repo = full_name.split("/", 1)
    if not owner or not repo:
        raise ValueError("full_name must be in owner/repo format")
    return owner, repo


def _lower_enum(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    return value.lower()


def _normalize_actor(actor: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(actor, dict):
        return None
    login = actor.get("login")
    if not isinstance(login, str):
        return None
    return {
        "login": login,
        "html_url": actor.get("url"),
        "avatar_url": actor.get("avatarUrl"),
    }


def _normalize_user_nodes(connection: Any) -> List[Dict[str, Any]]:
    nodes = connection.get("nodes") if isinstance(connection, dict) else None
    if not isinstance(nodes, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for node in nodes:
        user = _normalize_actor(node)
        if user is not None:
            normalized.append(user)
    return normalized


def _normalize_label_nodes(connection: Any) -> List[Dict[str, Any]]:
    nodes = connection.get("nodes") if isinstance(connection, dict) else None
    if not isinstance(nodes, list):
        return []
    labels: List[Dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        name = node.get("name")
        if not isinstance(name, str):
            continue
        labels.append(
            {
                "name": name,
                "color": node.get("color"),
                "description": node.get("description"),
            }
        )
    return labels


def _normalize_issue(node: Any) -> Dict[str, Any]:
    if not isinstance(node, dict):
        return {}
    milestone = node.get("milestone")
    milestone_payload = None
    if isinstance(milestone, dict):
        milestone_payload = {
            "title": milestone.get("title"),
            "state": _lower_enum(milestone.get("state")),
            "html_url": milestone.get("url"),
            "description": milestone.get("description"),
            "due_on": milestone.get("dueOn"),
            "created_at": milestone.get("createdAt"),
        }

    comments = node.get("comments") if isinstance(node.get("comments"), dict) else {}
    return {
        "id": node.get("databaseId"),
        "node_id": node.get("id"),
        "number": node.get("number"),
        "title": node.get("title"),
        "state": _lower_enum(node.get("state")),
        "html_url": node.get("url"),
        "url": node.get("url"),
        "created_at": node.get("createdAt"),
        "updated_at": node.get("updatedAt"),
        "closed_at": node.get("closedAt"),
        "body": node.get("body"),
        "user": _normalize_actor(node.get("author")),
        "labels": _normalize_label_nodes(node.get("labels")),
        "assignees": _normalize_user_nodes(node.get("assignees")),
        "comments": comments.get("totalCount"),
        "milestone": milestone_payload,
    }


def _normalize_pull_request(node: Any) -> Dict[str, Any]:
    if not isinstance(node, dict):
        return {}
    return {
        "id": node.get("databaseId"),
        "node_id": node.get("id"),
        "number": node.get("number"),
        "title": node.get("title"),
        "state": _lower_enum(node.get("state")),
        "draft": node.get("isDraft"),
        "html_url": node.get("url"),
        "created_at": node.get("createdAt"),
        "updated_at": node.get("updatedAt"),
        "user": _normalize_actor(node.get("author")),
        "head": {
            "ref": node.get("headRefName"),
            "repo": {"full_name": node.get("headRepository", {}).get("nameWithOwner")}
            if isinstance(node.get("headRepository"), dict)
            else None,
        },
        "base": {
            "ref": node.get("baseRefName"),
            "repo": {"full_name": node.get("baseRepository", {}).get("nameWithOwner")}
            if isinstance(node.get("baseRepository"), dict)
            else None,
        },
    }


def _normalize_workflow_run(node: Any) -> Dict[str, Any]:
    if not isinstance(node, dict):
        return {}
    workflow = node.get("workflow") if isinstance(node.get("workflow"), dict) else {}
    name = node.get("name") or workflow.get("name")
    return {
        "id": node.get("databaseId"),
        "node_id": node.get("id"),
        "name": name,
        "event": node.get("event"),
        "status": _lower_enum(node.get("status")),
        "conclusion": _lower_enum(node.get("conclusion")),
        "head_branch": node.get("headBranch"),
        "head_sha": node.get("headSha"),
        "created_at": node.get("createdAt"),
        "updated_at": node.get("updatedAt"),
        "html_url": node.get("url"),
    }


def _format_graphql_errors(errors: Any) -> Optional[str]:
    if not errors:
        return None
    if isinstance(errors, list):
        messages = [err.get("message") for err in errors if isinstance(err, dict)]
        filtered = [msg for msg in messages if isinstance(msg, str) and msg]
        if filtered:
            return "; ".join(filtered)
    if isinstance(errors, dict):
        message = errors.get("message")
        if isinstance(message, str):
            return message
    if isinstance(errors, str):
        return errors
    return "GraphQL request returned errors."


async def list_open_issues_graphql(
    full_name: str,
    state: Literal["open", "closed", "all"] = "open",
    per_page: int = 30,
    cursor: Optional[str] = None,
) -> Dict[str, Any]:
    """List issues using GraphQL, excluding pull requests."""

    if per_page <= 0:
        raise ValueError("per_page must be > 0")
    if per_page > 100:
        raise ValueError("per_page must be <= 100")

    owner, repo = _split_full_name(full_name)
    if state not in {"open", "closed", "all"}:
        raise ValueError("state must be 'open', 'closed', or 'all'")

    states: List[str]
    if state == "all":
        states = ["OPEN", "CLOSED"]
    else:
        states = [state.upper()]

    m = _main()
    response = await m.graphql_query(
        query=ISSUES_QUERY,
        variables={
            "owner": owner,
            "name": repo,
            "first": per_page,
            "after": cursor,
            "states": states,
        },
    )

    if not isinstance(response, dict):
        return {"error": "GraphQL response was not an object"}
    if response.get("error") or response.get("errors"):
        return response

    data = response.get("data")
    repo_data = data.get("repository") if isinstance(data, dict) else None
    issues_data = (
        repo_data.get("issues") if isinstance(repo_data, dict) else None
    ) or {}
    nodes = issues_data.get("nodes") if isinstance(issues_data, dict) else []
    page_info = issues_data.get("pageInfo") if isinstance(issues_data, dict) else {}

    issues = [_normalize_issue(node) for node in nodes if isinstance(node, dict)]

    return {
        "full_name": full_name,
        "state": state,
        "issues": issues,
        "total_count": issues_data.get("totalCount"),
        "page_info": {
            "has_next_page": page_info.get("hasNextPage")
            if isinstance(page_info, dict)
            else None,
            "end_cursor": page_info.get("endCursor")
            if isinstance(page_info, dict)
            else None,
        },
    }


async def list_workflow_runs_graphql(
    full_name: str,
    per_page: int = 30,
    cursor: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """List recent GitHub Actions workflow runs using GraphQL."""

    if per_page <= 0:
        raise ValueError("per_page must be > 0")
    if per_page > 100:
        raise ValueError("per_page must be <= 100")

    owner, repo = _split_full_name(full_name)

    m = _main()
    response = await m.graphql_query(
        query=WORKFLOW_RUNS_QUERY,
        variables={
            "owner": owner,
            "name": repo,
            "first": per_page,
            "after": cursor,
        },
    )

    if not isinstance(response, dict):
        return {"error": "GraphQL response was not an object"}
    if response.get("error") or response.get("errors"):
        return response

    data = response.get("data")
    repo_data = data.get("repository") if isinstance(data, dict) else None
    runs_data = (
        repo_data.get("workflowRuns") if isinstance(repo_data, dict) else None
    ) or {}
    nodes = runs_data.get("nodes") if isinstance(runs_data, dict) else []
    page_info = runs_data.get("pageInfo") if isinstance(runs_data, dict) else {}

    runs = [_normalize_workflow_run(node) for node in nodes if isinstance(node, dict)]
    if branch:
        runs = [run for run in runs if run.get("head_branch") == branch]

    return {
        "full_name": full_name,
        "branch": branch,
        "runs": runs,
        "total_count": runs_data.get("totalCount"),
        "page_info": {
            "has_next_page": page_info.get("hasNextPage")
            if isinstance(page_info, dict)
            else None,
            "end_cursor": page_info.get("endCursor")
            if isinstance(page_info, dict)
            else None,
        },
    }


async def list_recent_failures_graphql(
    full_name: str,
    branch: Optional[str] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """List recent failed/cancelled workflow runs using GraphQL."""

    if limit <= 0:
        raise ValueError("limit must be > 0")

    per_page = min(max(limit, 10), 50)

    runs_payload = await list_workflow_runs_graphql(
        full_name=full_name,
        per_page=per_page,
        cursor=None,
        branch=branch,
    )

    if runs_payload.get("error") or runs_payload.get("errors"):
        return runs_payload

    raw_runs = runs_payload.get("runs") if isinstance(runs_payload, dict) else []

    failure_conclusions = {
        "failure",
        "cancelled",
        "timed_out",
        "action_required",
        "startup_failure",
    }

    failures: List[Dict[str, Any]] = []
    for run in raw_runs:
        if not isinstance(run, dict):
            continue
        status = run.get("status")
        conclusion = run.get("conclusion")

        if conclusion in failure_conclusions:
            include = True
        elif status == "completed" and conclusion not in (
            None,
            "success",
            "neutral",
            "skipped",
        ):
            include = True
        else:
            include = False

        if not include:
            continue

        failures.append(run)
        if len(failures) >= limit:
            break

    return {
        "full_name": full_name,
        "branch": branch,
        "limit": limit,
        "runs": failures,
    }


async def get_repo_dashboard_graphql(
    full_name: str,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a compact dashboard using GraphQL as a fallback."""

    owner, repo = _split_full_name(full_name)

    issues_first = 10
    pulls_first = 10
    runs_first = 5
    tree_expression = f"{branch}:" if branch else "HEAD:"

    m = _main()
    response = await m.graphql_query(
        query=DASHBOARD_QUERY,
        variables={
            "owner": owner,
            "name": repo,
            "issuesFirst": issues_first,
            "pullsFirst": pulls_first,
            "runsFirst": runs_first,
            "treeExpression": tree_expression,
        },
    )

    if not isinstance(response, dict):
        return {"error": "GraphQL response was not an object"}
    if response.get("error"):
        return response

    errors = response.get("errors")
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    repo_data = data.get("repository") if isinstance(data, dict) else None

    repo_error = None
    if not isinstance(repo_data, dict):
        repo_error = _format_graphql_errors(errors) or "Repository data unavailable."
        repo_data = {}

    default_branch = (
        repo_data.get("defaultBranchRef", {}).get("name")
        if isinstance(repo_data.get("defaultBranchRef"), dict)
        else None
    )
    effective_branch = branch or default_branch

    repo_info = {
        "id": repo_data.get("nameWithOwner"),
        "full_name": repo_data.get("nameWithOwner"),
        "name": repo,
        "description": repo_data.get("description"),
        "html_url": repo_data.get("url"),
        "private": repo_data.get("isPrivate"),
        "archived": repo_data.get("isArchived"),
        "stargazers_count": repo_data.get("stargazerCount"),
        "forks_count": repo_data.get("forkCount"),
        "created_at": repo_data.get("createdAt"),
        "updated_at": repo_data.get("updatedAt"),
        "owner": {
            "login": repo_data.get("owner", {}).get("login")
            if isinstance(repo_data.get("owner"), dict)
            else None,
            "html_url": repo_data.get("owner", {}).get("url")
            if isinstance(repo_data.get("owner"), dict)
            else None,
        },
        "default_branch": default_branch,
    }

    prs_data = repo_data.get("pullRequests") if isinstance(repo_data, dict) else {}
    pr_nodes = prs_data.get("nodes") if isinstance(prs_data, dict) else []
    pull_requests = [
        _normalize_pull_request(node) for node in pr_nodes if isinstance(node, dict)
    ]

    issues_data = repo_data.get("issues") if isinstance(repo_data, dict) else {}
    issue_nodes = issues_data.get("nodes") if isinstance(issues_data, dict) else []
    issues = [_normalize_issue(node) for node in issue_nodes if isinstance(node, dict)]

    runs_data = repo_data.get("workflowRuns") if isinstance(repo_data, dict) else {}
    run_nodes = runs_data.get("nodes") if isinstance(runs_data, dict) else []
    workflows = [
        _normalize_workflow_run(node) for node in run_nodes if isinstance(node, dict)
    ]
    if effective_branch:
        workflows = [
            run for run in workflows if run.get("head_branch") == effective_branch
        ]

    tree_object = repo_data.get("object") if isinstance(repo_data, dict) else {}
    entries = tree_object.get("entries") if isinstance(tree_object, dict) else []
    top_level_tree: List[Dict[str, Any]] = []
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str):
                continue
            normalized_path = _normalize_repo_path_for_repo(full_name, name)
            size = None
            obj = entry.get("object") if isinstance(entry.get("object"), dict) else {}
            if isinstance(obj, dict):
                size = obj.get("byteSize")
            top_level_tree.append(
                {
                    "path": normalized_path,
                    "type": entry.get("type"),
                    "size": size,
                }
            )

    errors_message = _format_graphql_errors(errors)

    return {
        "branch": effective_branch,
        "repo": repo_info,
        "repo_error": repo_error,
        "pull_requests": pull_requests,
        "pull_requests_error": errors_message if not pull_requests else None,
        "issues": issues,
        "issues_error": errors_message if not issues else None,
        "workflows": workflows,
        "workflows_error": errors_message if not workflows else None,
        "top_level_tree": top_level_tree,
        "top_level_tree_error": errors_message if not top_level_tree else None,
    }
