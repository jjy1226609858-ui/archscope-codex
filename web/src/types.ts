export type Port = {
  id: string
  direction: 'in' | 'out'
  domain: string
  delegate?: { module: string; port: string }
}

export type GraphModule = {
  id: string
  name: string
  purpose: string
  kind: 'leaf' | 'composite'
  parent?: string
  ports: Port[]
  implementation_status: 'implemented' | 'not_ready' | 'structural' | 'historical_unknown'
  verification_status: string
  run_status: string
  runtime_summary?: RuntimeSummary
}

export type GraphEdge = {
  id: string
  source: string
  target: string
  source_port: string
  target_port: string
  kind: 'declared_data_flow'
  run_status: string
  description: string
}

export type RuntimeSummary = {
  inputs: Record<string, unknown>
  outputs: Record<string, unknown>
  error: null | { error_type?: string; message?: string }
  event_count: number
}

export type RuntimeEvent = {
  ingest_seq: number
  event_type: string
  module_id?: string
  flow_id?: string
  occurred_at: string
  payload: Record<string, unknown>
}

export type Operation = {
  operation_id: string
  run_id: string
  profile_id: string
  profile_label: string
  observation_enabled?: boolean
  observation_coverage?: string
  diagnostic_id?: string
  state: string
  exit_code?: number | null
  created_at: string
  finished_at?: string
  result?: Record<string, unknown>
  events?: RuntimeEvent[]
  event_count?: number
}

export type CheckDiagnostic = {
  diagnostic_id: string
  status: string
  message: string
  module_id?: string
  target_module_id?: string
  path?: string
  line?: number
  rule_id?: string
}

export type CheckReport = {
  check_id: string
  status: string
  acceptance_status: string
  freshness?: string
  ci_attestation?: { status: string; protection: string; diagnostic_id?: string }
  diagnostics: CheckDiagnostic[]
  coverage: { source_file_count: number; parsed_file_count: number }
}

export type ArchitectureProposal = {
  proposal_id: string
  state: string
  base_architecture_digest: string
  candidate_architecture_digest: string
  rationale: string
  diff: Record<string, { added: string[]; removed: string[]; changed: string[] }>
}

export type RepairTask = {
  task_id: string
  version: number
  state: string
  module_id: string
  objective: string
  evidence_refs: string[]
  allowed_files: string[]
  required_tests: string[]
  scope_approval?: { reviewer: string; approved_at: string } | null
  lease?: { actor_id: string; claimed_at: string; expires_at: string } | null
  verification?: {
    result: string
    ci_attestation_status?: string
    out_of_scope_files: string[]
    check: { status: string }
    tests: { status: string }
  } | null
}

export type TaskContext = {
  task: RepairTask
  freshness: {
    snapshot_digest: string
    changed_files: string[]
    out_of_scope_files: string[]
    architecture_unchanged: boolean
    lease_active: boolean
    realign_reason: string | null
  }
  evidence: { ref: string; kind?: string; status?: string | null; available: boolean; diagnostic_id?: string }[]
  claimable: boolean
}

export type GraphEnvelope = {
  api_version: string
  request_id: string
  project_id: string
  status: string
  architecture_digest: string
  code_digest: string
  diagnostics: unknown[]
  data: {
    project: {
      id: string
      name: string
      purpose: string
      open_questions: string[]
    }
    run_profiles: { id: string; label: string }[]
    historical: boolean
    architecture_revisions: { digest: string; name: string; historical: boolean }[]
    operation: Operation | null
    approval: { status: string; protection: string; diagnostic_id?: string }
    latest_check: CheckReport | null
    pending_proposals: ArchitectureProposal[]
    tasks: RepairTask[]
    nodes: GraphModule[]
    edges: GraphEdge[]
  }
}

export type ModuleEnvelope = {
  architecture_digest: string
  data: {
    module: GraphModule & {
      binding?: {
        files: string[]
        public_imports: string[]
        entries: { id: string; symbol: string }[]
      }
    }
    summary: {
      matched_files: string[]
      implementation_status: string
      verification_status: string
      run_status: string
    }
    runtime_summary?: RuntimeSummary
    run_id?: string
    children: string[]
    incoming_flows: GraphEdge[]
    outgoing_flows: GraphEdge[]
  }
}
