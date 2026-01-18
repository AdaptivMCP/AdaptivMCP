from __future__ import annotations

from typing import Any, Literal

from ._main import _main


async def get_rate_limit() -> dict[str, Any]:
    """Return the authenticated token's GitHub rate-limit document."""

    m = _main()
    return await m._github_request("GET", "/rate_limit")


async def get_user_login() -> dict[str, Any]:
    """Return the login for the authenticated GitHub user."""

    m = _main()

    data = await m._github_request("GET", "/user")
    login = None
    if isinstance(data.get("json"), dict):
        login = data["json"].get("login")
    return {
        "status_code": data.get("status_code"),
        "login": login,
        "user": data.get("json"),
    }


async def list_repositories(
    affiliation: str | None = None,
    visibility: str | None = None,
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    """List repositories accessible to the authenticated user."""

    m = _main()

    params: dict[str, Any] = {"per_page": per_page, "page": page}
    if affiliation:
        params["affiliation"] = affiliation
    if visibility:
        params["visibility"] = visibility
    return await m._github_request("GET", "/user/repos", params=params)


async def list_repositories_by_installation(
    installation_id: int,
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    """List repositories accessible via a specific GitHub App installation."""

    m = _main()

    params = {"per_page": per_page, "page": page}
    return await m._github_request(
        "GET",
        f"/user/installations/{installation_id}/repositories",
        params=params,
    )


async def create_repository(
    name: str,
    owner: str | None = None,
    owner_type: Literal["auto", "user", "org"] = "auto",
    description: str | None = None,
    homepage: str | None = None,
    visibility: Literal["public", "private", "internal"] | None = None,
    private: bool | None = None,
    auto_init: bool = True,
    gitignore_template: str | None = None,
    license_template: str | None = None,
    is_template: bool = False,
    has_issues: bool = True,
    has_projects: bool | None = None,
    has_wiki: bool = True,
    has_discussions: bool | None = None,
    team_id: int | None = None,
    security_and_analysis: dict[str, Any] | None = None,
    template_full_name: str | None = None,
    include_all_branches: bool = False,
    topics: list[str] | None = None,
    create_payload_overrides: dict[str, Any] | None = None,
    update_payload_overrides: dict[str, Any] | None = None,
    clone_to_workspace: bool = False,
    clone_ref: str | None = None,
) -> dict[str, Any]:
    """Create a new GitHub repository for the authenticated user or an organization.

    Designed to match GitHub's "New repository" UI with a safe escape hatch:

    - First-class params cover common fields.
    - create_payload_overrides and update_payload_overrides pass additional
    GitHub REST fields without waiting for server updates.

    Template-based creation is supported via template_full_name using:
    POST /repos/{template_owner}/{template_repo}/generate
    """

    m = _main()

    steps: list[str] = []
    warnings: list[str] = []

    try:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")
        name = name.strip()

        if visibility is not None and private is not None:
            inferred_private = visibility != "public"
            if inferred_private != private:
                raise ValueError("visibility and private disagree")

        if visibility is not None:
            effective_private = visibility != "public"
        elif private is not None:
            effective_private = bool(private)
        else:
            effective_private = False

        target_owner = owner.strip() if isinstance(owner, str) and owner.strip() else None
        authenticated_login: str | None = None

        # Resolve the authenticated user (needed for auto owner and template generation).
        if owner_type != "org" or template_full_name:
            user = await m._github_request("GET", "/user")
            if isinstance(user.get("json"), dict):
                authenticated_login = user["json"].get("login")
            if not target_owner:
                target_owner = authenticated_login

        if owner_type == "org" and not target_owner:
            raise ValueError("owner is required when owner_type='org'")

        use_org_endpoint = False
        if owner_type == "org":
            use_org_endpoint = True
        elif owner_type == "user":
            use_org_endpoint = False
            if target_owner and authenticated_login and target_owner != authenticated_login:
                warnings.append(
                    f"owner '{target_owner}' differs from authenticated user '{authenticated_login}'; using user endpoint"
                )
        else:
            # auto: if caller provided an owner different from auth login, assume org.
            if target_owner and authenticated_login and target_owner != authenticated_login:
                use_org_endpoint = True

        create_target_desc = (
            f"{target_owner}/{name}" if target_owner else f"(authenticated-user)/{name}"
        )

        def _apply_overrides(
            base: dict[str, Any], overrides: dict[str, Any] | None
        ) -> dict[str, Any]:
            if overrides and isinstance(overrides, dict):
                base.update(overrides)
            return base

        created_resp: dict[str, Any]
        create_payload: dict[str, Any]

        if template_full_name:
            if not isinstance(template_full_name, str) or "/" not in template_full_name:
                raise ValueError("template_full_name must look like 'owner/repo'")
            template_full_name = template_full_name.strip()

            steps.append(
                f"Creating repository from template {template_full_name} as {create_target_desc}."
            )
            create_payload = {
                "owner": target_owner,
                "name": name,
                "description": description,
                "private": effective_private,
                "include_all_branches": bool(include_all_branches),
            }
            create_payload = _apply_overrides(create_payload, create_payload_overrides)
            created_resp = await m._github_request(
                "POST",
                f"/repos/{template_full_name}/generate",
                json_body=create_payload,
            )
        else:
            endpoint = "/user/repos"
            if use_org_endpoint:
                endpoint = f"/orgs/{target_owner}/repos"

            steps.append(f"Creating repository {create_target_desc} via {endpoint}.")
            create_payload = {
                "name": name,
                "description": description,
                "homepage": homepage,
                "private": effective_private,
                "auto_init": bool(auto_init),
                "is_template": bool(is_template),
                "has_issues": bool(has_issues),
                "has_wiki": bool(has_wiki),
            }
            if visibility is not None:
                create_payload["visibility"] = visibility
            if gitignore_template:
                create_payload["gitignore_template"] = gitignore_template
            if license_template:
                create_payload["license_template"] = license_template
            if has_projects is not None:
                create_payload["has_projects"] = bool(has_projects)
            if has_discussions is not None:
                create_payload["has_discussions"] = bool(has_discussions)
            if team_id is not None:
                create_payload["team_id"] = int(team_id)
            if security_and_analysis is not None:
                create_payload["security_and_analysis"] = security_and_analysis

            create_payload = _apply_overrides(create_payload, create_payload_overrides)
            created_resp = await m._github_request("POST", endpoint, json_body=create_payload)

        repo_json = created_resp.get("json") if isinstance(created_resp, dict) else None
        full_name = repo_json.get("full_name") if isinstance(repo_json, dict) else None
        if not isinstance(full_name, str) or not full_name:
            if target_owner:
                full_name = f"{target_owner}/{name}"

        updated_resp = None
        if update_payload_overrides and full_name:
            steps.append(f"Applying post-create settings to {full_name}.")
            updated_resp = await m._github_request(
                "PATCH",
                f"/repos/{full_name}",
                json_body=dict(update_payload_overrides),
            )

        topics_resp = None
        if topics and full_name:
            cleaned = [t.strip() for t in topics if isinstance(t, str) and t.strip()]
            if cleaned:
                steps.append(f"Setting topics on {full_name}: {', '.join(cleaned)}.")
                topics_resp = await m._github_request(
                    "PUT",
                    f"/repos/{full_name}/topics",
                    json_body={"names": cleaned},
                    headers={"Accept": "application/vnd.github+json"},
                )

        workspace_dir = None
        if clone_to_workspace and full_name:
            steps.append(f"Cloning {full_name}@{clone_ref or 'default'} into workspace.")
            workspace_dir = await m._clone_repo(full_name, ref=clone_ref)

        return {
            "full_name": full_name,
            "repo": repo_json,
            "created": created_resp,
            "create_payload": create_payload,
            "updated": updated_resp,
            "topics": topics_resp,
            "workspace_dir": workspace_dir,
            "steps": steps,
            "warnings": warnings,
        }
    except Exception as exc:
        return m._structured_tool_error(exc, context="create_repository")
