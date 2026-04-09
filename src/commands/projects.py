"""Project budget commands: --add-project, --update-project, --projects, --delete-project, --reset-project."""

import os
import sys

from src.db import setup_database
from src.queries import (
    add_to_budget,
    compute_deadline_pressure,
    create_project_budget,
    delete_project_budget,
    delete_task_history_all,
    find_budget_by_name,
    get_all_active_budgets,
    reset_project_budget_hours,
    update_budget_fields,
)
from src.todoist_client import TodoistClient

_PRIORITY_LABEL = {4: "P1", 3: "P2", 2: "P3", 1: "P4"}
_PRIORITY_API = {"P1": 4, "P2": 3, "P3": 2, "P4": 1}


def _parse_session_range(s: str) -> tuple[int, int]:
    """Parse '90m-180m', '90-180', '1h-3h', '90m-3h' → (min_mins, max_mins)."""

    def to_minutes(part: str) -> int:
        part = part.strip().lower()
        if part.endswith("h"):
            return int(float(part[:-1]) * 60)
        elif part.endswith("m"):
            return int(part[:-1])
        else:
            return int(part)

    parts = s.split("-")
    if len(parts) != 2:
        raise ValueError(f"Invalid session format: '{s}'. Use MIN-MAX e.g. 90m-180m")
    return to_minutes(parts[0]), to_minutes(parts[1])


def _find_project_match(name: str) -> dict:
    """Find a single project_budgets row by case-insensitive name match."""
    matches = find_budget_by_name(name)
    if not matches:
        print(f"[ERROR] No project budget matching '{name}' found.")
        sys.exit(1)
    exact = [m for m in matches if m["project_name"].lower() == name.lower()]
    if len(exact) == 1:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    print(f"[ERROR] Ambiguous project name '{name}'. Matches:")
    for m in matches:
        print(f"  • {m['project_name']}")
    sys.exit(1)


def cmd_add_project(context: dict, args) -> None:
    """--add-project: create a long-running project budget in DB + Todoist."""
    import dateparser

    setup_database()

    name = args.add_project
    budget_hours = args.budget
    session_str = args.session or "60m-180m"
    deadline_str = args.deadline
    priority_label = (args.priority or "P2").upper()

    try:
        session_min, session_max = _parse_session_range(session_str)
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)

    deadline_iso = None
    if deadline_str:
        parsed = dateparser.parse(
            deadline_str,
            settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False},
        )
        if parsed is None:
            print(f"[ERROR] Could not parse deadline: '{deadline_str}'")
            sys.exit(1)
        deadline_iso = parsed.date().isoformat()

    priority_int = _PRIORITY_API.get(priority_label, 3)
    client = TodoistClient(os.getenv("TODOIST_API_TOKEN"))

    task_content = f"[Budget] {name}"
    try:
        task_id = client.create_task(
            content=task_content,
            priority=priority_int,
            deadline=deadline_iso,
            labels=["budget-task"],
        )
    except Exception as exc:
        print(f"[ERROR] Could not create Todoist task: {exc}")
        sys.exit(1)

    create_project_budget(
        todoist_task_id=task_id,
        project_name=name,
        total_budget_hours=budget_hours,
        session_min_minutes=session_min,
        session_max_minutes=session_max,
        deadline=deadline_iso,
        priority=priority_int,
    )

    print(f"\n  Project:   {name}")
    print(f"  Budget:    {budget_hours}h total")
    print(f"  Session:   {session_min}–{session_max}min")
    if deadline_iso:
        print(f"  Deadline:  {deadline_iso}")
    print(f"  Priority:  {priority_label}")
    print(f"  Task ID:   {task_id}")
    print(f"\n  Project budget created.")


def cmd_update_project(context: dict, args) -> None:
    """--update-project: patch budget hours, session range, or deadline."""
    import dateparser

    setup_database()
    name = args.update_project

    budgets = get_all_active_budgets()
    match = next(
        (b for b in budgets if b["project_name"].lower() == name.lower()), None
    )
    if match is None:
        matches = [b for b in budgets if name.lower() in b["project_name"].lower()]
        if len(matches) == 1:
            match = matches[0]
        elif len(matches) > 1:
            print(f"[ERROR] Ambiguous project name '{name}'. Matches:")
            for m in matches:
                print(f"  • {m['project_name']}")
            sys.exit(1)
        else:
            print(f"[ERROR] No active project budget matching '{name}'")
            sys.exit(1)

    task_id = match["todoist_task_id"]
    changed = False

    if args.add_budget is not None:
        new_rem = add_to_budget(task_id, float(args.add_budget))
        print(f"  Budget +{args.add_budget}h → {new_rem:.1f}h remaining")
        changed = True

    field_kw: dict = {}
    if args.set_session:
        try:
            smin, smax = _parse_session_range(args.set_session)
        except ValueError as exc:
            print(f"[ERROR] {exc}")
            sys.exit(1)
        field_kw["session_min_minutes"] = smin
        field_kw["session_max_minutes"] = smax
        print(f"  Session → {smin}–{smax}min")
        changed = True

    if args.set_deadline:
        parsed = dateparser.parse(
            args.set_deadline,
            settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False},
        )
        if parsed is None:
            print(f"[ERROR] Could not parse deadline: '{args.set_deadline}'")
            sys.exit(1)
        deadline_iso = parsed.date().isoformat()
        field_kw["deadline"] = deadline_iso
        print(f"  Deadline → {deadline_iso}")
        changed = True

    if field_kw:
        update_budget_fields(task_id, **field_kw)

    if changed:
        print(f"\n  Updated: {match['project_name']}")
    else:
        print(
            f"  Nothing to update. Use --add-budget, --set-session, or --set-deadline."
        )


def cmd_projects(context: dict) -> None:
    """--projects: display all active project budgets as a table."""
    setup_database()
    budgets = get_all_active_budgets()

    if not budgets:
        print("No active project budgets. Use --add-project to create one.")
        return

    _W = 76
    print(f"\n{'═' * _W}")
    print(f"  ACTIVE PROJECT BUDGETS")
    print(f"{'═' * _W}")
    print(
        f"  {'NAME':<26} {'REMAIN':>7} {'TOTAL':>7} {'SESSION':>13} {'DEADLINE':<12} {'PRESSURE':<10}"
    )
    print(f"  {'─' * 72}")

    for b in budgets:
        pressure = compute_deadline_pressure(b.get("deadline"), b["remaining_hours"])
        session_str = f"{b['session_min_minutes']}–{b['session_max_minutes']}min"
        deadline = b.get("deadline") or "—"
        print(
            f"  {b['project_name']:<26} "
            f"{b['remaining_hours']:>6.1f}h "
            f"{b['total_budget_hours']:>6.1f}h "
            f"{session_str:>13} "
            f"{deadline:<12} "
            f"{pressure:<10}"
        )

    print(f"{'═' * _W}\n")


def cmd_delete_project(context: dict, args) -> None:
    """--delete-project NAME [--keep-task]: remove a project budget entry."""
    setup_database()
    budget = _find_project_match(args.delete_project)
    keep_task = getattr(args, "keep_task", False)

    client = TodoistClient(os.getenv("TODOIST_API_TOKEN"))

    task_content = f"[Budget] {budget['project_name']}"
    try:
        t = client.get_task_by_id(budget["todoist_task_id"])
        if t:
            task_content = t.content
    except Exception:
        pass

    p_label = _PRIORITY_LABEL.get(budget.get("priority", 3), "P?")
    deadline = budget.get("deadline") or "none"
    session_str = f"{budget['session_min_minutes']}–{budget['session_max_minutes']}min"

    print(f"\n  Delete project budget: \"{budget['project_name']}\"")
    print(
        f"    Budget:   {budget['remaining_hours']:.1f}h of {budget['total_budget_hours']:.1f}h remaining"
    )
    print(
        f"    Sessions: {session_str}  |  Priority: {p_label}  |  Deadline: {deadline}"
    )
    print(f"    Todoist task: \"{task_content}\" (ID: {budget['todoist_task_id']})")
    if keep_task:
        print("    The Todoist task will be kept (unscheduled).")
    else:
        print("    The Todoist task will also be deleted.")

    try:
        confirm = input("\n  Confirm? [y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        confirm = "n"

    if confirm != "y":
        print("  Cancelled.")
        return

    delete_project_budget(budget["todoist_task_id"])
    delete_task_history_all(budget["todoist_task_id"])

    if keep_task:
        try:
            client.clear_task_due(budget["todoist_task_id"])
        except Exception as exc:
            print(f"  [WARN] Could not clear Todoist task schedule: {exc}")
        task_outcome = "Todoist task kept (unscheduled)."
    else:
        try:
            client.delete_task(budget["todoist_task_id"])
        except Exception as exc:
            print(f"  [WARN] Could not delete Todoist task: {exc}")
        task_outcome = "Todoist task deleted."

    print(f"\n  ✅ Project \"{budget['project_name']}\" deleted.")
    print(f"     {task_outcome}")


def cmd_reset_project(context: dict, args) -> None:
    """--reset-project NAME: reset remaining hours back to total budget."""
    setup_database()
    budget = _find_project_match(args.reset_project)

    print(f"\n  Reset \"{budget['project_name']}\" remaining hours?")
    print(
        f"    Current:    {budget['remaining_hours']:.1f}h remaining of {budget['total_budget_hours']:.1f}h"
    )
    print(
        f"    After reset: {budget['total_budget_hours']:.1f}h remaining of {budget['total_budget_hours']:.1f}h"
    )
    print("  Also clears all task_history rows for this project.")

    try:
        confirm = input("\n  Confirm? [y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        confirm = "n"

    if confirm != "y":
        print("  Cancelled.")
        return

    new_hours = reset_project_budget_hours(budget["todoist_task_id"])
    delete_task_history_all(budget["todoist_task_id"])

    client = TodoistClient(os.getenv("TODOIST_API_TOKEN"))
    try:
        client.clear_task_due(budget["todoist_task_id"])
    except Exception as exc:
        print(f"  [WARN] Could not clear Todoist task schedule: {exc}")

    print(f"\n  ✅ Project \"{budget['project_name']}\" reset to {new_hours:.1f}h.")
    print("     Run --plan-day to schedule a fresh session.")
