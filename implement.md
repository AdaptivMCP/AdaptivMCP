Closing the AI Knowledge Gap for the Adaptiv GitHub Controller
Observed Issues with AI Controller Usage

Role Confusion: The AI assistant often behaves like a tutor giving the user instructions, instead of directly executing tasks. It ends up asking the user to run commands or make edits, whereas it should be performing those actions itself via the controller tools
GitHub
. This indicates a fundamental misunderstanding of its role.

Improper Tool Usage: The assistant frequently misuses or guesses tool parameters and fails to follow the required JSON schema. For example, it struggles to compose correct arguments for file edits or searches (e.g. using wrong field names or formatting), leading to errors. The controller’s contract explicitly warns not to invent parameters and to obey each tool’s declared schema
GitHub
GitHub
, so this behavior shows the AI isn’t internalizing those rules.

Difficulty Editing Files: Even simple file modifications are problematic – the AI doesn’t create proper diffs or commits. Instead of using the provided diff-based commit tools, it might attempt clumsy inline edits or ask the user to apply changes. The controller expects the AI to treat multi-line edits as routine and use tools like apply_text_update_and_commit for changes
GitHub
. The assistant’s struggle here suggests it hasn’t fully learned the proper workflow for editing and committing changes on a feature branch.

These issues make the AI fall short of acting like a “professional AI developer”, as it’s neither following the established workflows nor taking autonomous initiative in the development process.

Root Cause: Assistant Not Following Controller Guidance

The underlying cause is a knowledge gap: the AI has not fully absorbed the Adaptiv Controller’s contract and workflow guidelines that dictate how it should behave. The Adaptiv Controller provides a rich set of tools and a “controller contract” precisely to align the assistant’s behavior. In fact, the controller_contract tool returns a versioned agreement “meant to reduce misunderstandings between ... assistants and the MCP server”, describing exactly how the AI should work with the tools and what workflows are expected
GitHub
. If the assistant isn’t using proper code or is confused about its role, it likely hasn’t internalized this contract and the associated docs.

In short, the AI doesn’t yet realize it is the developer in this setup. The controller’s documentation makes clear that “assistants using this controller are expected to behave like disciplined engineers... not like a generic chat bot”
GitHub
. Failing to read or remember these expectations leads to the misuse we see. Thus, to close this gap, we need to expose the assistant to the controller’s guidance in a systematic, enforceable way.

Solution: Strengthening the Controller Prompt & Workflow

To fix these problems, you should implement a more robust startup procedure and prompt strategy so the AI learns its role and the correct workflows from the get-go. Here is a concrete plan:

Adopt the Official Controller System Prompt: Start by using the provided Adaptiv Controller prompt (v1.0) as the AI’s system instructions. This prompt is specifically designed to clarify the assistant’s role and responsibilities. It tells the AI to “act like a careful, senior engineer,” to plan and execute tasks with the MCP tools, and never to ask the human to run commands or edit files
GitHub
. By embedding this into the AI’s system message or custom instructions, you set the correct expectations. Key points to include from this prompt:

The AI is fully responsible for using tools to carry out the work (no offloading work to the user)
GitHub
.

It should explain its plan briefly, then use tools to implement code changes, run tests, and so on end-to-end
GitHub
GitHub
.

It must prefer small, incremental changes with clear summaries, mimicking how a real developer works in steps
GitHub
.

This official prompt is available in docs/CONTROLLER_PROMPT_V1.md and is meant to be copy-pasted into your assistant’s system instructions
GitHub
GitHub
. Using it verbatim (or with minimal customization for your style) will give the AI a strong foundational understanding of how to behave.

Enforce the Startup Tool Calls (Discovery Phase): Along with the system prompt, ensure the assistant always performs the initial “bootstrapping” sequence when a session starts or context is lost. The Adaptiv workflow recommends that on first connection, the AI should immediately call a few tools to gather live info
GitHub
:

get_server_config: to check the server’s settings (especially whether writes are enabled) and default repo/branch
GitHub
.

controller_contract (compact=true): to fetch the latest controller contract, which concisely reminds the AI of all expectations, tool behaviors, and guardrails
GitHub
. The contract is the authoritative source of truth for how the assistant should proceed, so reading it at runtime aligns the AI with the actual server configuration and policies
GitHub
.

list_all_actions (include_parameters=true): to list every available tool and their input schemas
GitHub
. This teaches the AI what tools it can use (e.g. search, ensure_branch, apply_text_update_and_commit, etc.) and the exact JSON structure each expects. It can also call describe_tool("<tool_name>") for detailed schema of a specific tool if needed.

By programmatically retrieving this information, the AI won’t have to guess or rely on stale memory – it will learn about the controller in real time. You can implement this by nudging the model (via the system prompt or an initial user message in a new conversation) to perform these calls. For example, the prompt explicitly says “On your first tool use in a conversation... do this startup sequence”
GitHub
. Make sure the model sees this instruction so it knows to actually run those tools. Once done, the assistant will have a clear picture of the repo, the tools, and the rules before attempting any coding task.

Reiterate JSON Schema Discipline: The assistant needs to strictly follow the JSON formats and parameters that the tools expect. Many of its errors editing files come from malformatted arguments or wrong field names. The solution is twofold: knowledge and validation. After using list_all_actions, the AI will know the correct parameter names (for example, that file operations require full_name of the repo and path, not a made-up “repo” field). But to be safe, instruct it to validate its tool arguments before execution. The controller provides a validate_tool_args tool exactly for this purpose. The system prompt already includes a section mandating: “Never guess schema… Use exactly the parameter names and types documented… Always build literal JSON objects (no extra quotes or \n escapes)… and call validate_tool_args before important calls”
GitHub
GitHub
. Reinforce this in the prompt or through an example. In practice, the AI should:

Consult describe_tool for any unfamiliar tool to see required fields.

Construct the JSON args as an object (not as a raw string or Markdown snippet).

Run validate_tool_args with the tool name and args. Only proceed if it returns valid: true.

If validation fails, stop and correct the JSON instead of blindly retrying. The contract stresses: “stop guessing and fix the arguments to match the schema” on error
GitHub
.

By making this a habit, the assistant will stop making syntax mistakes or random parameter guesses, which addresses the “not using proper code” problem. This JSON discipline might slow it down initially, but it ultimately saves a lot of frustration by catching mistakes early. The result will be clean, correct tool calls (e.g. editing functions that work on the first try, because the AI used the right keys and formatting).

Use Branches and Diff-Based Edits for File Changes: To resolve the struggles with editing files, the assistant must follow the standard Git workflow enforced by the controller: work on a feature branch, and apply changes via diff/patch tools. You should remind or demonstrate to the AI the happy path for a simple edit: for example, create a branch, make the edit, commit, then open a PR. The controller’s documentation outlines this clearly for a “small documentation change” or a “single-file code change” scenario. A typical sequence (which the AI should emulate) is:

Call ensure_branch to create a new branch (e.g. "fix/some-bug") off of main
GitHub
GitHub
. The AI must not commit directly to main, as per safety rule #1
GitHub
. Emphasize that every non-trivial change should be on a separate branch – this prevents accidental direct writes and keeps changes reviewable.

Use get_file_contents (or get_file_slice for large files) to read the file that needs editing
GitHub
. The AI should gather context from the file and possibly related files (tests, usage references) before making changes – just like a human developer would read the code first.

Prepare the modifications. Instead of printing the diff or new code in Markdown for the user, the assistant should either generate a unified diff or the new file content internally. The recommended method for a straightforward edit is to call apply_text_update_and_commit with the updated file content
GitHub
. This single tool call will take the new content, create a commit on the branch, and even return a verification of the diff applied
GitHub
. For more complex multi-hunk edits or very large files, it can use build_unified_diff + apply_patch_and_commit – but the key is, it should utilize these controller-provided diff tools to apply changes, rather than attempting to manipulate the file via ad-hoc means.

Include a meaningful commit message. The tools usually have a parameter for commit message or automatically generate one; the AI should ensure the message is clear (e.g. “Fix off-by-one error in X calculation”).

Run tests if applicable. Before considering the task done, the assistant should use run_tests (or run_command with something like pytest) on that branch to verify nothing is broken
GitHub
. If tests fail, it should interpret the failures and fix the code accordingly, just like a real developer performing debugging. This addresses the “debug and update like a real developer” aspect – a professional AI developer should not assume code works without running tests. The contract explicitly states: “Whenever you change code or behavior, create or update tests… do not treat tests as optional.”
GitHub
. Encourage the AI to follow this ethos by always considering testing as part of the workflow (and adding new tests when fixing bugs or adding features).

Finally, open a pull request. The AI can call open_pr_for_existing_branch to create a PR from its feature branch into the default branch (usually main)
GitHub
. It should provide a concise title and description of the changes. This is the last step a human would do after committing; having the AI do it solidifies the analogy of it acting as a complete development agent.

By drilling these steps into the assistant (through the system prompt and by referencing the workflow docs), you “teach” it how to edit a file properly. No more asking the user to make changes or confusion about how to save edits – the AI will simply carry out the edit on a branch and commit it. The documentation even assures the assistant that routine edits are nothing exotic: “Treat routine multi-line edits as normal; rely on diff-based tools like apply_text_update_and_commit... instead of calling them tricky or offloading them to humans.”
GitHub
. In practice, once the AI goes through this a couple of times, it will start to treat it as the normal procedure for any code change.

Reinforce No-Offloading and Self-Reliance: Finally, make it clear that all development actions should be done by the AI through the controller, not by the end-user. This point cannot be stressed enough, since it was a primary issue. The assistant should never respond with “You (the user) should run X” or “Open your editor and change Y.” If it finds itself about to suggest the user do something, it should instead perform that action with the appropriate tool. The controller contract already includes this mandate: “Remember that only the assistant drives tool calls: do not ask humans to type commands, add blank lines, or re-run failed steps manually.”
GitHub
. Similarly, the system prompt says “Do not offload work back to the user… Use the MCP tools and workspace helpers instead.”
GitHub
. By keeping this rule in the forefront (possibly as a bullet in the prompt or an auto-reminder if the AI slips), you ensure the AI truly functions as an autonomous developer. If the AI tries to shift work to the user, that’s a sign it’s either unsure how to proceed or forgot the tools; in such cases, have it revisit the controller_contract or relevant docs rather than conclude that the user should intervene.

Implementing the above steps will close the knowledge gap by actively supplying the AI with the knowledge and context it was missing. Essentially, you are aligning the AI’s behavior with the controller’s design:

The system prompt gives it a firm understanding of its job (acting as a software engineer using tools, not a consultant).

The startup calls feed it real-time info about the repo, tools, and policies, so it doesn’t operate on false assumptions.

The schema and validation emphasis prevents the common errors that were tripping it up with JSON and tool usage.

The branch + diff workflow training ensures it knows how to make and commit changes correctly (no more confusion editing files).

Constant reminders to be self-sufficient keep it from reverting to generic ChatGPT habits.

Finally, since you plan to offer this as a product for others, it’s worth noting that these improvements should make the AI’s behavior reliable and professional across the board. Every new assistant using the controller should be introduced to the contract and workflow in this manner. In fact, you might automate this by always having the first conversation turn be something like: “(System) You are connected to Adaptiv Controller. Remember to follow the controller_contract and use tools.” or even programmatically triggering the get_server_config and controller_contract calls upon connection. This ensures any model (GPT-4, GPT-3.5, or future versions like the “ChatGPT” mode you mentioned) will immediately know how to behave.

By bridging the knowledge gap with explicit instructions and enforced best practices, the AI will begin to “create, debug, fix, and update like a real developer” — just as you envisioned. You should see it planning tasks, making code changes in your repo, running tests, and opening PRs with minimal confusion or human guidance, all while respecting the safety rails. Good luck, and happy coding with your AI developer!

Sources:

Adaptiv Controller README and Documentation – on expected assistant behavior and tooling (Proofgate-Revocations/chatgpt-mcp-github repository). Key excerpts include the controller contract and prompt guidelines that address these issues
GitHub
GitHub
GitHub
.