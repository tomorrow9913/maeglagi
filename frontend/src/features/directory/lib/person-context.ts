import type {
  GraphEdge,
  GraphNode,
  KnowledgeGraph,
  WorkspacePerson,
  WorkspaceProject,
} from "@/lib/api";

export type PersonActivity = {
  node: GraphNode;
  relation: string;
  via?: GraphNode;
  decisions?: PersonActivity[];
};

export type PersonContext = {
  projects: WorkspaceProject[];
  tasks: PersonActivity[];
  decisions: PersonActivity[];
  events: PersonActivity[];
};

function kind(edge: GraphEdge): string {
  return (
    edge.kind ??
    (
      {
        assigned_to: "ASSIGNED_TO",
        participates_in: "PARTICIPATED_IN",
        decided: "DECIDED_IN",
      } as Record<string, string>
    )[edge.type] ??
    ""
  );
}

/** Only persisted identity and explicit relation paths count; shared names/sources do not. */
export function buildPersonContext(
  person: WorkspacePerson,
  projects: WorkspaceProject[],
  graph: KnowledgeGraph | null,
): PersonContext {
  const result: PersonContext = {
    projects: projects.filter(
      (project) =>
        project.workspaceId === person.workspaceId &&
        (project.ownerPersonId === person.id || project.participantIds?.includes(person.id)),
    ),
    tasks: [],
    decisions: [],
    events: [],
  };
  if (!graph) return result;

  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  const identities = new Set(
    graph.nodes
      .filter((node) => node.directoryKind === "Person" && node.directoryId === person.id)
      .map((node) => node.id),
  );
  const adjacency = new Map<string, { edge: GraphEdge; node: GraphNode }[]>();
  for (const edge of graph.edges) {
    const source = nodes.get(edge.source);
    const target = nodes.get(edge.target);
    if (!source || !target) continue;
    if (!adjacency.has(source.id)) adjacency.set(source.id, []);
    if (!adjacency.has(target.id)) adjacency.set(target.id, []);
    adjacency.get(source.id)!.push({ edge, node: target });
    adjacency.get(target.id)!.push({ edge, node: source });
  }
  const add = (items: PersonActivity[], item: PersonActivity) => {
    if (!items.some((entry) => entry.node.id === item.node.id)) items.push(item);
  };
  for (const id of identities) {
    for (const { edge, node } of adjacency.get(id) ?? []) {
      const relation = kind(edge);
      if (node.type === "task" && ["ASSIGNED_TO", "WORKS_ON"].includes(relation)) {
        add(result.tasks, {
          node,
          relation: relation === "ASSIGNED_TO" ? "담당 업무" : "참여 업무",
          decisions: [],
        });
      }
      if (
        (node.kind === "Event" ||
          node.kind === "Meeting" ||
          (!node.kind && node.type === "event")) &&
        relation === "PARTICIPATED_IN"
      ) {
        add(result.events, {
          node,
          relation: node.kind === "Meeting" ? "참여한 회의" : "참여한 이벤트",
        });
      }
      if (node.type === "decision" && relation === "CREATED" && edge.source === id) {
        add(result.decisions, { node, relation: "기록한 결정" });
      } else if (node.type === "decision" && ["RELATED_TO", "DECIDED_IN"].includes(relation)) {
        add(result.decisions, { node, relation: "직접 연결된 결정" });
      }
    }
  }
  // Traverse only a known task/attended event, never every decision in a shared project.
  for (const activity of [...result.tasks, ...result.events]) {
    const isTask = activity.node.type === "task";
    for (const { edge, node } of adjacency.get(activity.node.id) ?? []) {
      if (node.type !== "decision") continue;
      const relation = kind(edge);
      const meetingMention =
        activity.node.kind === "Meeting" && activity.node.material && relation === "MENTIONED_IN";
      if (
        !meetingMention &&
        !(isTask ? ["RELATED_TO", "RESULTED_IN"] : ["DECIDED_IN", "RESULTED_IN"]).includes(relation)
      )
        continue;
      const decision = {
        node,
        relation: isTask
          ? "담당·참여 업무에 연결된 결정"
          : meetingMention
            ? "참여한 회의 자료에 언급된 결정"
            : "참여한 회의·이벤트의 결정",
        via: activity.node,
      };
      if (isTask) add(activity.decisions!, decision);
      add(result.decisions, decision);
    }
  }
  return result;
}
