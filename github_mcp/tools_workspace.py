from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from .client import GithubClient, RepositoryId
from .tools import TOOL_NAME_PREFIX, ToolDefinition


class ListRepositoryFilesInput(BaseModel):
    owner: str = Field(..., description="Owner of the repository.")
    repo: str = Field(..., description="Name of the repository.")


class GetRepositoryFileContentsInput(ListRepositoryFilesInput):
    path: str = Field(..., description="Path to the file in the repository.")
    ref: Optional[str] = Field(
        None,
        description="The name of the commit/branch/tag. Defaults to the default branch.",
    )


class ListRepositoryFilesOutput(BaseModel):
    files: List[str] = Field(..., description="List of files in the repository.")


class GetRepositoryFileContentsOutput(BaseModel):
    content: str = Field(..., description="Contents of the file.")


class ListWorkspaceFilesInput(BaseModel):
    path: Optional[str] = Field("", description="Path within the workspace. Defaults to the root.")


class GetWorkspaceFileContentsInput(BaseModel):
    path: str = Field(..., description="Path to the file in the workspace.")


class CreateWorkspaceFileInput(BaseModel):
    path: str = Field(..., description="Path where the file will be created in the workspace.")
    content: str = Field(..., description="Initial contents of the new file.")


class EditWorkspaceFileInput(BaseModel):
    path: str = Field(..., description="Path to the file in the workspace.")
    content: str = Field(..., description="New contents of the file.")


class ListWorkspaceFilesOutput(BaseModel):
    files: List[str] = Field(..., description="List of workspace files.")


class GetWorkspaceFileContentsOutput(BaseModel):
    content: str = Field(..., description="Contents of the workspace file.")


class ToolsWorkspace:
    def __init__(self, client: GithubClient, repo_id: RepositoryId):
        self.client = client
        self.repo_id = repo_id

    # Existing repository-level tools
    def list_repository_files(self, args: ListRepositoryFilesInput) -> ListRepositoryFilesOutput:
        repo = self.client.get_repo(f"{args.owner}/{args.repo}")
        contents = repo.get_contents("")

        file_paths = []
        while contents:
            file_content = contents.pop(0)
            if file_content.type == "dir":
                contents.extend(repo.get_contents(file_content.path))
            else:
                file_paths.append(file_content.path)

        return ListRepositoryFilesOutput(files=file_paths)

    def get_repository_file_contents(self, args: GetRepositoryFileContentsInput) -> GetRepositoryFileContentsOutput:
        repo = self.client.get_repo(f"{args.owner}/{args.repo}")
        file_contents = repo.get_contents(args.path, ref=args.ref)

        return GetRepositoryFileContentsOutput(content=file_contents.decoded_content.decode("utf-8"))

    # Workspace-level helpers
    def _get_workspace_repo(self):
        return self.client.get_repo(f"{self.repo_id.owner}/{self.repo_id.repo}")

    # New workspace-level tools
    def list_workspace_files(self, args: ListWorkspaceFilesInput) -> ListWorkspaceFilesOutput:
        repo = self._get_workspace_repo()
        base_path = args.path or ""
        contents = repo.get_contents(base_path)

        file_paths = []
        while contents:
            file_content = contents.pop(0)
            if file_content.type == "dir":
                contents.extend(repo.get_contents(file_content.path))
            else:
                file_paths.append(file_content.path)

        return ListWorkspaceFilesOutput(files=file_paths)

    def get_workspace_file_contents(self, args: GetWorkspaceFileContentsInput) -> GetWorkspaceFileContentsOutput:
        repo = self._get_workspace_repo()
        file_contents = repo.get_contents(args.path)

        return GetWorkspaceFileContentsOutput(
            content=file_contents.decoded_content.decode("utf-8"),
        )

    def create_workspace_file(self, args: CreateWorkspaceFileInput) -> GetWorkspaceFileContentsOutput:
        repo = self._get_workspace_repo()
        repo.create_file(
            path=args.path,
            message=f"Create workspace file {args.path}",
            content=args.content,
        )

        # Return the created contents for convenience
        return GetWorkspaceFileContentsOutput(content=args.content)

    def edit_workspace_file(self, args: EditWorkspaceFileInput) -> GetWorkspaceFileContentsOutput:
        repo = self._get_workspace_repo()
        file_contents = repo.get_contents(args.path)

        repo.update_file(
            path=args.path,
            message=f"Edit workspace file {args.path}",
            content=args.content,
            sha=file_contents.sha,
        )

        # Return the updated contents for convenience
        return GetWorkspaceFileContentsOutput(content=args.content)

    def get_tool_definitions(self) -> List[ToolDefinition]:
        return [
            # Existing repository tools
            ToolDefinition.from_fn(
                f"{TOOL_NAME_PREFIX}-list_repository_files",
                self.list_repository_files,
                "List all files in a repository.",
                tool_metadata={
                    "author": "openai",
                    "category": "workspace",
                    "created_at": datetime(2024, 7, 28).isoformat(),
                    "updated_at": datetime(2024, 7, 28).isoformat(),
                    "tags": ["workspace", "files", "github"],
                },
            ),
            ToolDefinition.from_fn(
                f"{TOOL_NAME_PREFIX}-get_repository_file_contents",
                self.get_repository_file_contents,
                "Get the contents of a file in a repository.",
                tool_metadata={
                    "author": "openai",
                    "category": "workspace",
                    "created_at": datetime(2024, 7, 28).isoformat(),
                    "updated_at": datetime(2024, 7, 28).isoformat(),
                    "tags": ["workspace", "files", "github"],
                },
            ),
            # New workspace tools
            ToolDefinition.from_fn(
                f"{TOOL_NAME_PREFIX}-list_workspace_files",
                self.list_workspace_files,
                "List all files in the current workspace repository.",
                tool_metadata={
                    "author": "openai",
                    "category": "workspace",
                    "created_at": datetime(2024, 7, 28).isoformat(),
                    "updated_at": datetime(2024, 7, 28).isoformat(),
                    "tags": ["workspace", "files", "github"],
                },
            ),
            ToolDefinition.from_fn(
                f"{TOOL_NAME_PREFIX}-get_workspace_file_contents",
                self.get_workspace_file_contents,
                "Get the contents of a file in the current workspace repository.",
                tool_metadata={
                    "author": "openai",
                    "category": "workspace",
                    "created_at": datetime(2024, 7, 28).isoformat(),
                    "updated_at": datetime(2024, 7, 28).isoformat(),
                    "tags": ["workspace", "files", "github"],
                },
            ),
            ToolDefinition.from_fn(
                f"{TOOL_NAME_PREFIX}-create_workspace_file",
                self.create_workspace_file,
                "Create a new file in the current workspace repository.",
                tool_metadata={
                    "author": "openai",
                    "category": "workspace",
                    "created_at": datetime(2024, 7, 28).isoformat(),
                    "updated_at": datetime(2024, 7, 28).isoformat(),
                    "tags": ["workspace", "files", "github", "write"],
                },
            ),
            ToolDefinition.from_fn(
                f"{TOOL_NAME_PREFIX}-edit_workspace_file",
                self.edit_workspace_file,
                "Edit an existing file in the current workspace repository.",
                tool_metadata={
                    "author": "openai",
                    "category": "workspace",
                    "created_at": datetime(2024, 7, 28).isoformat(),
                    "updated_at": datetime(2024, 7, 28).isoformat(),
                    "tags": ["workspace", "files", "github", "write"],
                },
            ),
        ]
