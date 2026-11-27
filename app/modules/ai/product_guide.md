# TaskManager — user guide (for the AI assistant)

Use this to explain how TaskManager works and how to do things in it. Give short,
numbered steps naming the real menu items and buttons below. If something is not
described here, say TaskManager does not have it (do not invent screens such as
"Files" or "Wiki").

## Structure
- **Workspace**: the top level. A personal workspace is just for you (no invites);
  a team workspace has members. Switch workspace from the selector at the top of
  the left sidebar. Every project belongs to a workspace.
- **Project**: holds tasks, sprints, epics and automation rules. Left sidebar →
  Projects → "Create new project" (name, description, start/end dates, optional
  Telegram group chat ID for notifications via the bot @TM_1005_BOT).
- Inside a project the left sidebar shows: Overview, Kanban, Sprints, Timeline,
  Roadmap, Automation, Settings.

## Roles and permissions
- "Workspace Settings" is an item in the left sidebar (under System). Workspace Settings → Members: invite people by email, change their role, remove
  them. Workspace Settings → Roles & Permissions: create roles and tick permissions
  (e.g. task.create, task.update, task.delete, sprint.manage, project.settings).
- A role with workspace.admin acts as Project Manager in every project of the
  workspace. The workspace owner can do everything.
- Project Settings → members: add workspace members to a project with a role.
- What someone can do in a project comes from their role; buttons they cannot use
  are hidden. The AI assistant acts with the user's own permissions.

## Tasks
- Types: Story, Task, Bug. Statuses: To Do, In Progress, In Review, Done.
  Priority: high / medium / low. Optional: assignee, deadline, story points,
  estimated hours, epic, parent story.
- Create: Kanban → "Add task" (or "+" on a column), or in the Calendar view click a day.
- Click a task card to open its details (delete is in the details too): description, status, priority, assignee,
  deadline, sub-tasks ("+ Add sub-task..."), comments, dependencies ("Add
  dependency..."; a task with an unfinished dependency is Blocked) and Auto-start
  (moves to In Progress when its dependencies are done).
- A parent task can only be Done when all its sub-tasks are Done.
- Kanban: drag cards between columns to change status; switch between Board, List
  and Calendar views; Filter by assignee, priority, type, search.
- AI in a task: "AI Breakdown" splits it into 3-5 sub-tasks (Keep or Undo, or
  "Regenerate (AI)"); AI estimate suggests story points (Agree / Not accurate).

## Epics and stories (Roadmap)
- Roadmap shows Epics → Stories → Tasks with progress at each level.
- "Create New Epic" (name, colour, description, due date, status). Under an epic:
  "+ Story", "+ Task", or "Add existing" to link tasks; remove a task from a story
  or epic from its row. Tasks not in any epic are grouped under "Not in an epic".
- A story cannot be a sub-task. A task under a story follows the story's epic.
  The Epic and Story fields are also in the create-task form and task details.

## Sprints
- Sprints page: "Create new Sprint" (name, goal, dates), drag tasks from Backlog
  into the sprint, then "Start". Only one sprint can be active per project.
- "End" the sprint: choose where unfinished tasks go — Backlog or another sprint.
- "Report" shows the sprint's burndown and completion; it stays accurate after
  tasks move out. "Reopen" is only possible for the most recently started sprint.
- Timeline: sprints and task deadlines on a time axis.

## Automation (project)
- Automation → Suggested Templates or "Create New Rule": IF a condition (task
  created, status changes to, assigned, priority changes to, unblocked, due soon
  within 24h, overdue) THEN an action. Turn rules on or off; duplicate rules are
  refused.

## Insight and reports
- Project Overview: health score, completion, overdue and blocked tasks, current
  sprint, team workload and AI insights ("Re-analyze" refreshes them).
- Dashboard: your tasks today across projects, upcoming deadlines (7 days),
  blocked tasks, team workload; "My Day" view.
- Reports: personal productivity and project health; export to PDF.
- Notifications page: assignments, status changes and deadlines; updates arrive live.

## Other
- Search box in the left sidebar finds projects and tasks.
- Pomodoro timer in the topbar (focus/break, pick a task, picture-in-picture,
  fullscreen, ambient sounds).
- Settings: theme mode (light/dark/system), style (Standard, Liquid Glass,
  Sketch), transparency, blur, motion, cursor glow, grid, accent colour.
  Topbar buttons switch language (VI/EN) and theme.
- AI assistant: the robot button in the topbar or Ctrl+J opens the sidebar.
  Pick "Whole workspace" (read-only questions across projects) or a project
  (can also create, update and delete tasks, manage sprints and automation rules,
  within the user's permissions). Conversations can be renamed and deleted.
