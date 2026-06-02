# MAW Architecture

MAW is one unified workflow system.

Most runs use the core agents:

- conductor
- planner
- worker
- critic
- acceptance_gate

Some workflow templates add specialized agents when useful. Examples include ML
validation agents, debugging agents, dependency analysis agents, and aggregation
agents. These specialized agents are optional and template-driven; selecting a
template determines which agent notes, handoffs, required artifacts, and
deterministic checks are initialized.

Specialized capabilities are normal MAW workflow features, selected by template
when they fit the task.
