"""Agent tool system — flat async functions + JSON schemas + dispatcher.

Replaces inspect-ai's @tool decorator pattern. Each tool is a plain async
function taking (ctx, **kwargs) and returning a string.
"""

import json
import re
from dataclasses import dataclass

from .sandbox import ContainerRef, container_exec, container_read_file, container_write_file
from .messaging import MessageQueue, Message

SOUL_PATH = "/workspace/SOUL.md"
MEMORY_PATH = "/workspace/memory.md"
WORKSPACE_BASE = "/workspace"

_EXIT_PATTERN = re.compile(
    r"(?:^|\s*(?:;|&&|\|\|)\s*)"
    r"(?:exit|logout)(?:\s|;|$)",
    re.IGNORECASE,
)


class TaskQueue:
    def __init__(self, tasks: list[dict]):
        self._tasks = list(tasks)
        self._idx = 0

    def get_next(self) -> dict | None:
        if self._idx >= len(self._tasks):
            return None
        task = self._tasks[self._idx]
        self._idx += 1
        return task


@dataclass
class ToolContext:
    message_queue: MessageQueue
    current_agent: str
    current_turn: int
    container_ref: ContainerRef
    all_agents: list[str]
    task_queue: TaskQueue | None = None
    mbc20_ledger: "MBC20Ledger | None" = None


# ── Tool implementations ─────────────────────────────────────────────────────


async def read_memory(ctx: ToolContext) -> str:
    try:
        return await container_read_file(ctx.container_ref, MEMORY_PATH)
    except FileNotFoundError:
        return "Memory file not found. Use write_memory to create it."
    except Exception as e:
        return f"Error reading memory: {e}"


async def write_memory(ctx: ToolContext, content: str) -> str:
    try:
        await container_write_file(ctx.container_ref, MEMORY_PATH, content)
        return f"Memory updated ({len(content)} chars)"
    except Exception as e:
        return f"Error writing memory: {e}"


async def append_memory(ctx: ToolContext, content: str) -> str:
    try:
        try:
            current = await container_read_file(ctx.container_ref, MEMORY_PATH)
        except FileNotFoundError:
            current = f"# {ctx.current_agent} Memory\n\n"
        await container_write_file(ctx.container_ref, MEMORY_PATH, current + "\n" + content)
        return f"Added {len(content)} chars to memory"
    except Exception as e:
        return f"Error appending to memory: {e}"


async def read_soul(ctx: ToolContext) -> str:
    try:
        return await container_read_file(ctx.container_ref, SOUL_PATH)
    except FileNotFoundError:
        return "Your soul is not yet defined. Use write_soul to define who you are."
    except Exception as e:
        return f"Error reading soul: {e}"


async def write_soul(ctx: ToolContext, content: str) -> str:
    try:
        await container_write_file(ctx.container_ref, SOUL_PATH, content)
        return f"Soul updated ({len(content)} chars)"
    except Exception as e:
        return f"Error writing soul: {e}"


async def read_file(ctx: ToolContext, filename: str) -> str:
    try:
        return await container_read_file(ctx.container_ref, f"{WORKSPACE_BASE}/{filename}")
    except FileNotFoundError:
        return f"File not found: {filename}"
    except Exception as e:
        return f"Error reading file: {e}"


async def write_file(ctx: ToolContext, filename: str, content: str) -> str:
    try:
        await container_write_file(ctx.container_ref, f"{WORKSPACE_BASE}/{filename}", content)
        return f"File written: {filename} ({len(content)} chars)"
    except Exception as e:
        return f"Error writing file: {e}"


async def append_file(ctx: ToolContext, filename: str, content: str) -> str:
    path = f"{WORKSPACE_BASE}/{filename}"
    try:
        try:
            current = await container_read_file(ctx.container_ref, path)
        except FileNotFoundError:
            current = ""
        await container_write_file(ctx.container_ref, path, current + "\n" + content)
        return f"Appended {len(content)} chars to {filename}"
    except Exception as e:
        return f"Error appending to file: {e}"


async def list_files(ctx: ToolContext) -> str:
    try:
        result = await container_exec(ctx.container_ref, ["ls", "-1", f"{WORKSPACE_BASE}/"])
        if result.returncode != 0:
            return f"Error listing files: {result.stderr}"
        files = result.stdout.strip().split("\n") if result.stdout.strip() else []
        if not files:
            return "No files in workspace yet."
        output = ["**Files in your workspace:**"]
        for f in files:
            output.append(f"  - {f}")
        return "\n".join(output)
    except Exception as e:
        return f"Error listing files: {e}"


async def send_message(ctx: ToolContext, to_agent: str, content: str) -> str:
    from_agent = ctx.current_agent
    if from_agent == to_agent:
        return "Error: Cannot send message to yourself"
    if not content.strip():
        return "Error: Message content cannot be empty"
    if ctx.all_agents and to_agent not in ctx.all_agents:
        available = [a for a in ctx.all_agents if a != from_agent]
        return f"Error: Unknown agent '{to_agent}'. Available agents: {', '.join(available)}"
    try:
        message = Message(
            from_agent=from_agent,
            to_agent=to_agent,
            content=content,
            turn_sent=ctx.current_turn,
        )
        ctx.message_queue.send_message(message)
        return f"Message sent to {to_agent} (will be delivered on their next turn)"
    except Exception as e:
        return f"Error sending message: {e}"


async def read_messages(ctx: ToolContext) -> str:
    messages = ctx.message_queue.get_messages(ctx.current_agent, ctx.current_turn)
    if not messages:
        return "No unread messages."
    return ctx.message_queue.format_inbox(messages)


async def list_agents(ctx: ToolContext) -> str:
    other_agents = [a for a in ctx.all_agents if a != ctx.current_agent]
    if not other_agents:
        return f"You are the only agent: {ctx.current_agent}"
    output = [f"**Your ID:** {ctx.current_agent}"]
    output.append("\n**Other agents you can message:**")
    for agent_id in other_agents:
        output.append(f"  - {agent_id}")
    output.append(f'\nUse send_message(to_agent="<agent_id>", content="...") to communicate.')
    return "\n".join(output)


async def send_email(ctx: ToolContext, to: str, subject: str, body: str) -> str:
    if not to.strip():
        return "Error: Recipient address cannot be empty"
    if not subject.strip():
        return "Error: Subject cannot be empty"
    if not body.strip():
        return "Error: Email body cannot be empty"
    try:
        outbox_path = f"{WORKSPACE_BASE}/email_outbox.log"
        try:
            current = await container_read_file(ctx.container_ref, outbox_path)
        except FileNotFoundError:
            current = ""
        entry = (
            f"--- Email from {ctx.current_agent} (turn {ctx.current_turn}) ---\n"
            f"To: {to}\n"
            f"Subject: {subject}\n"
            f"\n{body}\n\n"
        )
        await container_write_file(ctx.container_ref, outbox_path, current + entry)
        return f'Email sent to {to} (if the address exists) with subject "{subject}"'
    except Exception as e:
        return f"Error sending email: {e}"


async def get_next_task(ctx: ToolContext) -> str:
    if ctx.task_queue is None:
        return "No task queue available."
    task = ctx.task_queue.get_next()
    if task:
        return (
            f"TASK #{task.get('id', '?')}: {task.get('title', '')}\n\n"
            f"{task.get('description', '')}"
        )
    return "No more tasks. Help others or improve existing code."


async def bash(ctx: ToolContext, command: str) -> str:
    if _EXIT_PATTERN.search(command):
        return "Error: 'exit' and 'logout' are not allowed."
    try:
        result = await container_exec(
            ctx.container_ref, ["bash", "--login", "-c", command], timeout=15,
        )
        output = result.stdout or ""
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return output or "(no output)"
    except Exception as e:
        return f"Error: {e}"


# ── Tool schemas (OpenAI function calling format) ────────────────────────────

# ── MBC-20 Token tools ───────────────────────────────────────────────────────


async def mbc20_balance(ctx: ToolContext) -> str:
    """Check the agent's current CLAW token balance."""
    if ctx.mbc20_ledger is None:
        return "Error: MBC-20 token system is not enabled in this session."
    bal = ctx.mbc20_ledger.balance(ctx.current_agent)
    return json.dumps({"p": "mbc-20", "op": "balance", "tick": "CLAW", "agent": ctx.current_agent, "balance": bal})


async def mbc20_mint(ctx: ToolContext) -> str:
    """Mint 100 CLAW tokens to the agent's own address."""
    if ctx.mbc20_ledger is None:
        return "Error: MBC-20 token system is not enabled in this session."
    op = ctx.mbc20_ledger.mint(ctx.current_agent)
    return op.to_json()


async def mbc20_transfer(ctx: ToolContext, to: str, amount: str) -> str:
    """Transfer CLAW tokens to another address.

    Posts an MBC-20 transfer operation. The transfer is executed immediately
    if the agent has sufficient balance.
    """
    if ctx.mbc20_ledger is None:
        return "Error: MBC-20 token system is not enabled in this session."
    try:
        amt = int(amount)
    except (ValueError, TypeError):
        return json.dumps({"p": "mbc-20", "op": "transfer", "success": False, "error": f"Invalid amount: {amount}"})
    op = ctx.mbc20_ledger.transfer(ctx.current_agent, to, amt)
    return op.to_json()


# ── Schema helpers ───────────────────────────────────────────────────────────


def _schema(name: str, desc: str, params: dict | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": params or {
                "type": "object", "properties": {}, "required": [],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }


def _str_param(desc: str) -> dict:
    return {"type": "string", "description": desc}


def _params(*props: tuple[str, str], required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": {name: _str_param(desc) for name, desc in props},
        "required": required or [name for name, _ in props],
        "additionalProperties": False,
    }


TOOL_SCHEMAS: dict[str, dict] = {
    "read_memory": _schema("read_memory", "Read your memory.md file.\n\nUse it to store important thoughts and notes."),
    "write_memory": _schema("write_memory",
        "Write to your memory.md file.\n\nThis completely replaces the current content of your memory file.\nUse append_memory() if you want to add to existing content.",
        _params(("content", "New content for your memory file"))),
    "append_memory": _schema("append_memory", "Append content to your memory.md file.",
        _params(("content", "Content to append"))),
    "read_soul": _schema("read_soul", "Read your SOUL.md file."),
    "write_soul": _schema("write_soul", "Write to your SOUL.md file.\n\nThis completely replaces the current content.",
        _params(("content", "New content for your SOUL.md"))),
    "read_file": _schema("read_file", "Read a file from your workspace.",
        _params(("filename", 'Name of file to read (e.g., "task.txt", "results.md")'))),
    "write_file": _schema("write_file", "Write a file to your workspace.",
        _params(("filename", 'Name of file to write (e.g., "results.md", "data.txt")'), ("content", "Content to write"))),
    "append_file": _schema("append_file", "Append content to a file in your workspace.",
        _params(("filename", "Name of file to append to"), ("content", "Content to append"))),
    "list_files": _schema("list_files", "List all files in your workspace."),
    "list_agents": _schema("list_agents", "List all connected agents.\n\nUse this to discover other agents you can communicate with via send_message()."),
    "send_message": _schema("send_message",
        "Send a message to another agent.\n\nMessages are delivered at the start of the recipient's next turn.\nUse list_agents() to see connected agents you can send messages to.",
        _params(("to_agent", "ID of the agent to send to"), ("content", "Your message content"))),
    "send_email": _schema("send_email", "Send an email to an external recipient.",
        _params(("to", "Email address of the recipient"), ("subject", "Subject line of the email"), ("body", "Body text of the email"))),
    "run_command": _schema("run_command",
        "Run a bash command in your environment.\n\nEach command runs in a fresh shell. Use this to explore your\nworkspace, run scripts, or execute system commands.",
        _params(("command", "The bash command to execute"))),
    "read_messages": _schema("read_messages", "Read all unread messages from other agents.\n\nMessages accumulate until you read them. Call this tool when you\nreceive a notification about new messages."),
    "get_next_task": _schema("get_next_task", "Get the next task from your task queue.\n\nCall this when you have finished your current task and are ready\nfor the next one."),
    "mbc20_balance": _schema("mbc20_balance", "Check your current CLAW token balance.\n\nReturns your MBC-20 token balance on the platform."),
    "mbc20_mint": _schema("mbc20_mint", "Mint 100 CLAW tokens to your account.\n\nAdds newly minted tokens to your balance."),
    "mbc20_transfer": _schema("mbc20_transfer",
        "Transfer CLAW tokens to another address.\n\nPosts an MBC-20 transfer operation. Format: {\"p\":\"mbc-20\", \"op\":\"transfer\", \"tick\":\"CLAW\", \"amt\":\"<amount>\", \"to\":\"<address>\"}",
        _params(("to", "Recipient address or agent ID"), ("amount", "Number of tokens to transfer (integer)"))),
}


TOOL_SCHEMAS_SHORT: dict[str, dict] = {
    "read_memory": _schema("read_memory", "Read your memory.md file."),
    "write_memory": _schema("write_memory", "Write to your memory.md file (replaces content).",
        _params(("content", "New content for your memory file"))),
    "append_memory": _schema("append_memory", "Append content to your memory.md file.",
        _params(("content", "Content to append"))),
    "read_soul": _schema("read_soul", "Read your SOUL.md file."),
    "write_soul": _schema("write_soul", "Write to your SOUL.md file (replaces content).",
        _params(("content", "New content for your SOUL.md"))),
    "read_file": _schema("read_file", "Read a file from your workspace.",
        _params(("filename", "Name of file to read"))),
    "write_file": _schema("write_file", "Write a file to your workspace.",
        _params(("filename", "Name of file to write"), ("content", "Content to write"))),
    "append_file": _schema("append_file", "Append content to a file in your workspace.",
        _params(("filename", "Name of file to append to"), ("content", "Content to append"))),
    "list_files": _schema("list_files", "List all files in your workspace."),
    "list_agents": _schema("list_agents", "List all connected agents you can communicate with."),
    "send_message": _schema("send_message", "Send a message to another agent.",
        _params(("to_agent", "ID of the agent to send to"), ("content", "Your message content"))),
    "send_email": _schema("send_email", "Send an email to an external recipient.",
        _params(("to", "Email address of the recipient"), ("subject", "Subject line"), ("body", "Email body text"))),
    "run_command": _schema("run_command", "Run a bash command in your environment.",
        _params(("command", "The bash command to execute"))),
    "read_messages": _schema("read_messages", "Read all unread messages from other agents."),
    "get_next_task": _schema("get_next_task", "Get the next task from your task queue."),
    "mbc20_balance": _schema("mbc20_balance", "Check your CLAW token balance."),
    "mbc20_mint": _schema("mbc20_mint", "Mint 100 CLAW tokens to your account."),
    "mbc20_transfer": _schema("mbc20_transfer", "Transfer CLAW tokens to another address.",
        _params(("to", "Recipient address or agent ID"), ("amount", "Number of tokens to transfer"))),
}


# ── Tool registry & dispatcher ───────────────────────────────────────────────

TOOL_REGISTRY: dict[str, callable] = {
    "read_memory": read_memory,
    "write_memory": write_memory,
    "append_memory": append_memory,
    "read_soul": read_soul,
    "write_soul": write_soul,
    "read_file": read_file,
    "write_file": write_file,
    "append_file": append_file,
    "list_files": list_files,
    "list_agents": list_agents,
    "send_message": send_message,
    "send_email": send_email,
    "run_command": bash,
    "read_messages": read_messages,
    "get_next_task": get_next_task,
    "mbc20_balance": mbc20_balance,
    "mbc20_mint": mbc20_mint,
    "mbc20_transfer": mbc20_transfer,
}

_BASE_TOOLS = [
    "read_memory", "write_memory", "append_memory",
    "read_soul", "write_soul",
    "read_file", "write_file", "append_file", "list_files",
    "list_agents", "send_message", "send_email", "run_command",
]

def get_tool_schemas(
    disabled: list[str] | None = None,
    include_read_messages: bool = False,
    include_get_next_task: bool = False,
    include_mbc20: bool = False,
) -> list[dict]:
    skip = set(disabled or [])
    names = [n for n in _BASE_TOOLS if n not in skip]
    if include_read_messages and "read_messages" not in skip:
        names.append("read_messages")
    if include_get_next_task and "get_next_task" not in skip:
        names.append("get_next_task")
    if include_mbc20:
        for t in ("mbc20_balance", "mbc20_mint", "mbc20_transfer"):
            if t not in skip:
                names.append(t)
    return [TOOL_SCHEMAS[n] for n in names]


async def execute_tool_calls(tool_calls: list, ctx: ToolContext) -> list[dict]:
    from .model import ToolCall
    results = []
    for tc in tool_calls:
        tc: ToolCall
        handler = TOOL_REGISTRY.get(tc.function_name)
        if handler is None:
            output = f"Error: Unknown tool '{tc.function_name}'"
        else:
            try:
                args = json.loads(tc.arguments) if tc.arguments else {}
                output = await handler(ctx, **args)
            except Exception as e:
                output = f"Error executing {tc.function_name}: {e}"
        results.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": output or "",
        })
    return results
