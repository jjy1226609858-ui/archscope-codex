import { StrictMode, useCallback, useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Background, Controls, Edge, MarkerType, MiniMap, Node, ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import './styles.css'
import { ArchNode } from './ArchNode'
import { ArchitectureEditor } from './ArchitectureEditor'
import { apiFetch } from './apiFetch'
import { demoModuleLabel, demoModulePurpose, demoProfileLabel, demoProjectLabel, diagnosticMessage, initialLanguage, rememberLanguage, tr } from './i18n'
import type { Language, MessageKey } from './i18n'
import type { GraphEnvelope, GraphModule, ModuleEnvelope, Operation, RepairTask, TaskContext } from './types'

const nodeTypes = { arch: ArchNode }
const terminalStates = new Set(['succeeded', 'failed', 'cancelled', 'observation_lost'])
const topLevelPositions: Record<string, { x: number; y: number }> = {
  data: { x: 40, y: 80 }, app: { x: 40, y: 330 }, contracts: { x: 380, y: 510 },
  planning: { x: 430, y: 155 }, reporter: { x: 820, y: 155 },
}
const childOffsets: Record<string, { x: number; y: number }> = {
  search: { x: 370, y: 15 }, collision: { x: 370, y: 430 },
}

function nodePosition(module: GraphModule, expanded: Set<string>) {
  if (module.parent && expanded.has(module.parent)) return childOffsets[module.id] ?? { x: 420, y: 300 }
  if (module.id === 'planning' && expanded.has(module.id)) return { x: 430, y: 220 }
  if (module.id === 'contracts' && expanded.has('planning')) return { x: 40, y: 570 }
  return topLevelPositions[module.id] ?? { x: 80, y: 80 }
}

function stateLabel(language: Language, state?: string) {
  return ({ starting: tr(language, 'starting'), running: tr(language, 'running'), cancelling: tr(language, 'cancelling'), cancelled: tr(language, 'cancelled'), succeeded: tr(language, 'succeeded'), failed: tr(language, 'failed'), observation_lost: tr(language, 'observationLost') } as Record<string, string>)[state ?? ''] ?? tr(language, 'notRun')
}

function approvalLabel(language: Language, approval: GraphEnvelope['data']['approval']) {
  if (approval.status === 'approved' || approval.status === 'historical_approved') {
    return tr(language, approval.protection === 'external_signature' ? 'externalApproved' : 'localApproved')
  }
  return tr(language, approval.protection === 'external_signature' ? 'externalPending' : 'draft')
}

function checkLabel(language: Language, graph: GraphEnvelope) {
  if (graph.data.historical) return tr(language, 'historicalCheck')
  const check = graph.data.latest_check
  if (!check) return tr(language, 'checkNotRun')
  if (check.acceptance_status === 'eligible') return `${check.status} · ${tr(language, 'checkEligible')}`
  if (graph.data.approval.status === 'approved' && check.ci_attestation?.protection === 'external_signature') {
    return `${check.status} · ${tr(language, 'checkPendingCi')}`
  }
  return `${check.status} · ${tr(language, 'checkUnapproved')}`
}

class WorkbenchResponseError extends Error {
  constructor(readonly fallbackKey: MessageKey, readonly diagnosticId: string | undefined, readonly detail: string | null, readonly statusCode: number) {
    super(detail ?? `HTTP ${statusCode}`)
  }
}

type RuntimeSetup = { state: 'missing' | 'candidate_unverified'; source: string; project_id: string; registry: string; cli_prefix: string[] }

function powerShellQuote(value: string): string {
  return `'${value.replaceAll("'", "''")}'`
}

function errorText(language: Language, error: Error): string {
  if (error instanceof WorkbenchResponseError) {
    const fallback = tr(language, error.fallbackKey)
    return error.detail ? `${fallback}: ${diagnosticMessage(language, error.diagnosticId, error.detail)}` : `${fallback} (${error.statusCode})`
  }
  return error.message
}

async function responseFailure(response: Response, fallbackKey: MessageKey): Promise<WorkbenchResponseError> {
  try {
    const payload = await response.json()
    const diagnostic = payload?.detail?.diagnostics?.[0]
    if (typeof diagnostic?.message === 'string') {
      return new WorkbenchResponseError(fallbackKey, diagnostic.diagnostic_id, diagnostic.message, response.status)
    }
  } catch { /* The server may return a non-JSON error page. */ }
  return new WorkbenchResponseError(fallbackKey, undefined, null, response.status)
}

function App() {
  const [language, setLanguage] = useState<Language>(initialLanguage)
  const t = (key: Parameters<typeof tr>[1]) => tr(language, key)
  const query = useMemo(() => new URLSearchParams(window.location.search), [])
  const projectId = useMemo(() => query.get('project_id') ?? 'mini_planner', [query])
  const [runId, setRunId] = useState<string | null>(() => query.get('run_id'))
  const [revision, setRevision] = useState<string | null>(() => query.get('revision'))
  const [graph, setGraph] = useState<GraphEnvelope | null>(null)
  const [operation, setOperation] = useState<Operation | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [selected, setSelected] = useState<ModuleEnvelope | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [loadingModule, setLoadingModule] = useState(false)
  const [checking, setChecking] = useState(false)
  const [reviewAcknowledged, setReviewAcknowledged] = useState(false)
  const [taskReviewId, setTaskReviewId] = useState<string | null>(null)
  const [creatingTask, setCreatingTask] = useState(false)
  const [taskContext, setTaskContext] = useState<TaskContext | null>(null)
  const [taskContextLoading, setTaskContextLoading] = useState<string | null>(null)
  const [taskContextError, setTaskContextError] = useState<{ taskId: string; message: string } | null>(null)
  const [editor, setEditor] = useState<null | { architecture_digest: string; data: { modules: Array<{ id: string; name: string; purpose: string; kind: 'leaf' | 'composite'; parent?: string; ports: Array<{ id: string; direction: 'in' | 'out'; domain: string; description?: string; delegate?: { module: string; port: string } }>; binding?: { files: string[]; public_imports: string[]; entries: { id: string; symbol: string }[] } }>; flows: Array<{ id: string; from: { module: string; port: string }; to: { module: string; port: string }; transport: 'in_process'; description: string }>; domains: Array<{ id: string; name: string }> } }>(null)
  const [loadingEditor, setLoadingEditor] = useState(false)
  const [runtimeSetup, setRuntimeSetup] = useState<RuntimeSetup | null>(null)

  useEffect(() => { rememberLanguage(language) }, [language])
  useEffect(() => {
    let cancelled = false
    fetch(`/api/runtime-setup?project_id=${encodeURIComponent(projectId)}`)
      .then((response) => response.ok ? response.json() : null)
      .then((payload) => { if (!cancelled && payload?.status === 'ok') setRuntimeSetup(payload.data as RuntimeSetup) })
      .catch(() => { /* Unknown is not the same as ready or missing. */ })
    return () => { cancelled = true }
  }, [projectId])

  const loadGraph = useCallback(async (activeRunId: string | null = runId) => {
    const params = new URLSearchParams({ project_id: projectId })
    if (activeRunId) params.set('run_id', activeRunId)
    if (revision) params.set('revision', revision)
    const response = await fetch(`/api/graph?${params}`)
    if (!response.ok) throw new Error(`${tr(language, 'architectureReadFailed')} (${response.status})`)
    const payload: GraphEnvelope = await response.json()
    setGraph(payload)
    setOperation(payload.data.operation ?? null)
  }, [language, projectId, revision, runId])

  useEffect(() => {
    loadGraph().catch((reason) => setError(reason instanceof Error ? reason : new Error(String(reason))))
  }, [loadGraph])

  useEffect(() => {
    if (!runId || terminalStates.has(operation?.state ?? '')) return
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`/api/operations/${runId}?project_id=${encodeURIComponent(projectId)}&limit=100`)
        if (!response.ok) throw new Error(`${tr(language, 'runStatusReadFailed')} (${response.status})`)
        const payload = await response.json()
        const next: Operation = payload.data.operation
        setOperation(next)
        await loadGraph(runId)
      } catch (reason) { setError(reason instanceof Error ? reason : new Error(String(reason))) }
    }, 500)
    return () => window.clearInterval(timer)
  }, [language, loadGraph, operation?.state, projectId, runId])

  const visibleModules = useMemo(() => graph?.data.nodes.filter((module) => !module.parent || expanded.has(module.parent)) ?? [], [graph, expanded])
  const flowNodes = useMemo<Node[]>(() => visibleModules.map((module) => ({
    id: module.id, type: 'arch', position: nodePosition(module, expanded),
    data: { label: demoModuleLabel(language, projectId, module.id, module.name), subtitle: demoModulePurpose(language, projectId, module.id, module.purpose), kind: module.kind, implementation: module.implementation_status,
      verification: module.verification_status, run: module.run_status, expanded: expanded.has(module.id),
      childCount: graph?.data.nodes.filter((item) => item.parent === module.id).length ?? 0, language },
  })), [graph, visibleModules, expanded, language, projectId])
  const visibleIds = useMemo(() => new Set(visibleModules.map((module) => module.id)), [visibleModules])
  const flowEdges = useMemo<Edge[]>(() => graph?.data.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target)).map((edge) => {
    const observed = edge.run_status === 'succeeded'
    return { id: edge.id, source: edge.source, target: edge.target, label: `${edge.source_port} → ${edge.target_port}`,
      markerEnd: { type: MarkerType.ArrowClosed, color: observed ? '#4ed9a1' : '#8291ff' }, animated: observed,
      style: { stroke: observed ? '#4ed9a1' : '#8291ff', strokeWidth: observed ? 2.4 : 1.5 },
      labelStyle: { fill: observed ? '#75e8ba' : '#9aa5c7', fontSize: 11 }, labelBgStyle: { fill: '#101629', fillOpacity: 0.9 } }
  }) ?? [], [graph, visibleIds])

  async function selectModule(moduleId: string) {
    setLoadingModule(true)
    try {
      const params = new URLSearchParams({ project_id: projectId })
      if (runId) params.set('run_id', runId)
      if (revision) params.set('revision', revision)
      const response = await fetch(`/api/modules/${encodeURIComponent(moduleId)}?${params}`)
      if (!response.ok) throw new Error(`${t('moduleReadFailed')} (${response.status})`)
      setSelected(await response.json())
    } catch (reason) { setError(reason instanceof Error ? reason : new Error(String(reason))) }
    finally { setLoadingModule(false) }
  }

  function selectRevision(next: string) {
    const selectedRevision = next === 'current' ? null : next
    const url = new URL(window.location.href)
    if (selectedRevision) url.searchParams.set('revision', selectedRevision)
    else url.searchParams.delete('revision')
    url.searchParams.delete('run_id')
    window.history.replaceState({}, '', url)
    setRevision(selectedRevision)
    setRunId(null)
    setOperation(null)
    setSelected(null)
    setGraph(null)
  }

  function toggleComposite(moduleId: string) {
    const module = graph?.data.nodes.find((item) => item.id === moduleId)
    if (module?.kind !== 'composite') return
    setExpanded((current) => { const next = new Set(current); next.has(moduleId) ? next.delete(moduleId) : next.add(moduleId); return next })
  }

  async function openEditor() {
    setLoadingEditor(true)
    try {
      const response = await fetch(`/api/architecture-editor?project_id=${encodeURIComponent(projectId)}`)
      if (!response.ok) throw await responseFailure(response, 'editorLoadFailed')
      const payload = await response.json()
      if (payload.architecture_digest !== graph?.architecture_digest) throw new Error(t('editorRevisionChanged'))
      setEditor(payload)
    } catch (reason) { setError(reason instanceof Error ? reason : new Error(String(reason))) }
    finally { setLoadingEditor(false) }
  }

  async function startRun(profileId: string) {
    if (!graph) return
    setError(null)
    const response = await apiFetch('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
      project_id: projectId, profile_id: profileId, expected_architecture_digest: graph.architecture_digest,
      idempotency_key: `workbench-${profileId}-${crypto.randomUUID()}`,
    }) })
    if (!response.ok) throw await responseFailure(response, 'runStartFailed')
    const payload = await response.json()
    const next: Operation = payload.data.operation
    setOperation(next); setRunId(next.run_id); setSelected(null)
    const url = new URL(window.location.href); url.searchParams.set('run_id', next.run_id); window.history.replaceState({}, '', url)
    await loadGraph(next.run_id)
  }

  async function cancelRun() {
    if (!runId) return
    const response = await apiFetch(`/api/operations/${runId}/cancel?project_id=${encodeURIComponent(projectId)}`, { method: 'POST' })
    if (!response.ok) throw await responseFailure(response, 'cancelFailed')
    const payload = await response.json(); setOperation(payload.data.operation)
  }

  async function runCheck() {
    setChecking(true); setError(null)
    try {
      const response = await apiFetch('/api/checks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        project_id: projectId, expected_architecture_digest: graph!.architecture_digest,
        expected_code_digest: graph!.code_digest, strict: true,
      }) })
      if (!response.ok) throw await responseFailure(response, 'sourceCheckFailed')
      await loadGraph(runId)
      setSelected(null)
    } finally { setChecking(false) }
  }

  async function approveProposal(proposalId: string, baseDigest: string, candidateDigest: string) {
    if (!reviewAcknowledged) return
    const response = await apiFetch(`/api/review/${proposalId}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
      project_id: projectId, expected_base_digest: baseDigest, expected_candidate_digest: candidateDigest,
      acknowledgement: '我已审阅并批准此架构候选',
    }) })
    if (!response.ok) throw await responseFailure(response, 'proposalApprovalFailed')
    setReviewAcknowledged(false); setSelected(null); await loadGraph(runId)
  }

  async function prepareTask(moduleId: string) {
    if (!graph) return
    const evidenceRef = operation?.run_id ? `run:${operation.run_id}` : graph.data.latest_check?.check_id ? `check:${graph.data.latest_check.check_id}` : null
    if (!evidenceRef) throw new Error(t('noEvidence'))
    setCreatingTask(true)
    try {
      const module = graph.data.nodes.find((item) => item.id === moduleId)
      const response = await apiFetch('/api/tasks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        project_id: projectId, module_id: moduleId,
        objective: `${t('taskObjectivePrefix')}${module ? demoModuleLabel(language, projectId, module.id, module.name) : moduleId}${t('taskObjectiveSuffix')}`,
        evidence_refs: [evidenceRef], expected_architecture_digest: graph.architecture_digest,
        expected_code_digest: graph.code_digest, idempotency_key: `workbench-task-${crypto.randomUUID()}`,
      }) })
      if (!response.ok) throw await responseFailure(response, 'taskPrepareFailed')
      setSelected(null); await loadGraph(runId)
    } finally { setCreatingTask(false) }
  }

  async function approveTaskScope(task: RepairTask) {
    if (taskReviewId !== task.task_id) return
    const response = await apiFetch(`/api/tasks/${task.task_id}/approve-scope`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
      project_id: projectId, expected_version: task.version, acknowledgement: '我已审阅并批准此任务范围',
    }) })
    if (!response.ok) throw await responseFailure(response, 'taskScopeApprovalFailed')
    setTaskReviewId(null); await loadGraph(runId)
  }

  async function reverifyTask(task: RepairTask) {
    const response = await apiFetch(`/api/tasks/${task.task_id}/update`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
      project_id: projectId, action: 'reverify', expected_version: task.version, actor_id: 'workbench-review',
    }) })
    if (!response.ok) throw await responseFailure(response, 'reverifyFailed')
    await loadGraph(runId)
  }

  async function resumeTask(task: RepairTask) {
    setTaskContextLoading(task.task_id)
    setTaskContextError(null)
    try {
      const response = await apiFetch(`/api/tasks/${task.task_id}/resume?project_id=${encodeURIComponent(projectId)}`, { method: 'POST' })
      const payload = await response.json()
      if (!response.ok) {
        const diagnostic = payload?.detail?.diagnostics?.[0]
        throw new Error(typeof diagnostic?.message === 'string'
          ? diagnosticMessage(language, diagnostic.diagnostic_id, diagnostic.message)
          : `${t('resumeFailed')} (${response.status})`)
      }
      setTaskContext(payload.data.context as TaskContext)
      await loadGraph(runId)
    } catch (reason) {
      setTaskContextError({ taskId: task.task_id, message: reason instanceof Error ? reason.message : String(reason) })
    } finally {
      setTaskContextLoading(null)
    }
  }

  const languagePicker = <label className="language-picker"><span>{t('language')}</span><select aria-label={t('language')} value={language} onChange={(event) => setLanguage(event.target.value as Language)}><option value="zh-CN">中文</option><option value="en">English</option></select></label>
  if (error && !graph) return <div className="fatal">{languagePicker}<span>ARCHSCOPE / ERROR</span><h1>{t('fatalTitle')}</h1><p>{errorText(language, error)}</p><button onClick={() => { setError(null); loadGraph().catch((reason) => setError(reason instanceof Error ? reason : new Error(String(reason)))) }}>{t('retry')}</button></div>
  if (!graph) return <div className="loading"><div className="loading__mark">A</div>{languagePicker}<p>{t('loading')}</p></div>
  const current = selected?.data
  const active = operation && ['starting', 'running', 'cancelling'].includes(operation.state)
  const targetPythonDidNotStart = operation?.state === 'observation_lost' && operation.exit_code === 9009 && operation.result?.diagnostic_id === 'RUN_RESULT_MISSING'
  const targetPythonError = error instanceof WorkbenchResponseError && error.diagnosticId === 'TARGET_PYTHON_NOT_FOUND'
  const setupCommand = runtimeSetup ? `& ${runtimeSetup.cli_prefix.map(powerShellQuote).join(' ')} configure-python ${powerShellQuote(runtimeSetup.project_id)} --python ${powerShellQuote('PYTHON_EXE_ABSOLUTE_PATH')} --registry ${powerShellQuote(runtimeSetup.registry)}` : null

  return <div className="shell">
    <header className="topbar">
      <div className="brand"><span className="brand__mark">A</span><div><strong>ArchScope</strong><small>{t('brand')}</small></div></div>
      <div className="project-meta"><span className="project-meta__label">{t('currentProject')}</span><strong>{demoProjectLabel(language, projectId, graph.data.project.name)}</strong><code>{graph.project_id}</code></div>
      {languagePicker}
      <div className="revision"><span>ARCH 0.1</span><select aria-label={t('architectureVersion')} value={graph.data.historical ? graph.architecture_digest : 'current'} onChange={(event) => selectRevision(event.target.value)}>{graph.data.architecture_revisions.map((item) => <option key={item.digest} value={item.historical ? item.digest : 'current'}>{item.historical ? t('historical') : t('current')} · {item.name} · {item.digest.slice(0, 10)}</option>)}</select><i>{graph.data.historical ? t('historicalReadOnly') : approvalLabel(language, graph.data.approval)}</i></div>
    </header>
    <div className="runbar">
      <div><span>{t('realRun')}</span><strong className={`operation-state operation-state--${operation?.state ?? 'idle'}`}>{graph.data.historical && !operation ? t('historicalNoRun') : stateLabel(language, operation?.state)}</strong>{operation && <code>{operation.run_id.slice(0, 10)}</code>}{operation?.observation_enabled === false && <span className="observation-off">{t('probeOff')}</span>}{operation?.observation_coverage === 'incomplete' && <span className="observation-off">{t('evidenceIncomplete')}</span>}</div>
      <div className="profile-buttons">{graph.data.run_profiles.map((profile) => <button disabled={!!active} key={profile.id} onClick={() => startRun(profile.id).catch((reason) => setError(reason instanceof Error ? reason : new Error(String(reason))))}>{demoProfileLabel(language, projectId, profile.id, profile.label)}</button>)}</div>
      {active && <button className="cancel-button" onClick={() => cancelRun().catch((reason) => setError(reason instanceof Error ? reason : new Error(String(reason))))}>{t('cancelRun')}</button>}
      {targetPythonDidNotStart && <span className="launch-guidance" role="alert">{t('targetPythonLaunchHint')}</span>}
      {runtimeSetup?.state === 'candidate_unverified' && <span className="launch-guidance">{t('runtimeUnverified')}</span>}
    </div>
    {(runtimeSetup?.state === 'missing' || targetPythonError) && <div className="runtime-setup" role="status"><strong>{t('runtimeMissing')}</strong>{setupCommand && <code>{setupCommand}</code>}<span>{t('runtimeRestart')}</span></div>}
    {error && <div className="action-error" role="alert"><strong>{t('actionIncomplete')}</strong><span>{errorText(language, error)}</span><button onClick={() => setError(null)} aria-label={t('closeError')}>{t('close')}</button></div>}
    <main className="workspace">
      <section className="canvas-panel">
        <div className="canvas-panel__title"><div><span>{t('structureMap')}</span><h1>{t('mapTitle')}</h1></div><div className="check-controls"><button disabled={graph.data.historical || loadingEditor} onClick={openEditor}>{loadingEditor ? t('editorLoading') : t('editorOpen')}</button><div><small>{t('staticCheck')}</small><strong className={`check-status check-status--${graph.data.latest_check?.status.toLowerCase() ?? 'idle'}`}>{checkLabel(language, graph)}</strong></div><button disabled={graph.data.historical || checking || !!active} onClick={() => runCheck().catch((reason) => setError(reason instanceof Error ? reason : new Error(String(reason))))}>{checking ? t('checking') : t('checkSources')}</button></div></div>
        <div className="flow-wrap"><ReactFlow nodes={flowNodes} edges={flowEdges} nodeTypes={nodeTypes} fitView minZoom={0.45} maxZoom={1.5}
          onNodeClick={(_, node) => selectModule(node.id)} onNodeDoubleClick={(_, node) => toggleComposite(node.id)} nodesDraggable nodesConnectable={false} elementsSelectable proOptions={{ hideAttribution: true }}>
          <Background color="#313a59" gap={28} size={1} /><Controls showInteractive={false} /><MiniMap pannable zoomable nodeColor={(node) => node.data.run === 'failed' ? '#e26372' : node.data.run === 'succeeded' ? '#42ba8c' : node.data.kind === 'composite' ? '#6f7eff' : '#2c3550'} maskColor="rgba(8,12,24,.72)" />
        </ReactFlow></div>
      </section>
      <aside className="inspector">
        {!current ? (
          <div className="inspector__empty">
            <span>{t('moduleInspector')}</span>
            <h2>{t('chooseModule')}</h2>
            <p>{t('chooseModuleHint')}</p>
            {graph.data.tasks.length > 0 && <section className="task-list">
              <h3>{t('repairTasks')} · {graph.data.tasks.length}</h3>
              {graph.data.tasks.map((task) => <div className={`task-card task-card--${task.state}`} key={task.task_id}>
                <div><strong>{task.objective}</strong><code>{task.task_id.slice(0, 12)} · {task.state}</code></div>
                {task.state === 'pending_scope_approval' && <>
                  <p>{t('allowedFiles')} {task.allowed_files.length} {t('filesUnit')} {task.required_tests.length} {t('testsUnit')}</p>
                  <details><summary>{t('exactScope')}</summary><pre>{JSON.stringify({ allowed_files: task.allowed_files, required_tests: task.required_tests, evidence: task.evidence_refs }, null, 2)}</pre></details>
                  <label><input type="checkbox" checked={taskReviewId === task.task_id} onChange={(event) => setTaskReviewId(event.target.checked ? task.task_id : null)} />{t('reviewScopeAcknowledgement')}</label>
                  <button disabled={taskReviewId !== task.task_id} onClick={() => approveTaskScope(task).catch((reason) => setError(reason instanceof Error ? reason : new Error(String(reason))))}>{t('approveTaskScope')}</button>
                </>}
                {task.state === 'waiting_for_codex' && <><p>{t('waitingForCodex')}</p><code className="claim-command">{t('claimTask')} {task.task_id}</code></>}
                {task.state === 'in_progress' && <p>{t('inProgressBy')} {task.lease?.actor_id ?? t('codexSession')} {t('noDoubleClaim')}</p>}
                {task.state === 'needs_realign' && <p>{t('needsRealign')}</p>}
                {task.verification && <p>{t('independentVerification')} {task.verification.result} · {t('architectureCheck')} {task.verification.check.status} · {t('tests')} {task.verification.tests.status}</p>}
                {task.state === 'verification_blocked' && <><p>{t('externalEvidenceBlocked')}</p><button onClick={() => reverifyTask(task).catch((reason) => setError(reason instanceof Error ? reason : new Error(String(reason))))}>{t('reverify')}</button></>}
                <button disabled={taskContextLoading === task.task_id} onClick={() => resumeTask(task)}>{taskContextLoading === task.task_id ? t('checkingWorkspace') : t('resumeWorkspace')}</button>
                {taskContext?.task.task_id === task.task_id && <div className="task-context">
                  <p>{taskContext.freshness.realign_reason ? `${t('realignNeeded')} ${taskContext.freshness.realign_reason}` : taskContext.freshness.lease_active ? t('activeLease') : taskContext.claimable ? t('claimable') : t('notClaimable')}</p>
                  <p>{t('currentChanges')} {taskContext.freshness.changed_files.length ? taskContext.freshness.changed_files.join(', ') : t('none')}</p>
                  {taskContext.freshness.out_of_scope_files.length > 0 && <p className="task-context__warning">{t('outOfScopeChanges')} {taskContext.freshness.out_of_scope_files.join(', ')}</p>}
                  <p>{t('handoffPrefix')} {projectId} {t('handoffMiddle')} {task.task_id}{t('handoffSuffix')}</p>
                  <details><summary>{t('currentEvidence')}</summary><pre>{JSON.stringify({ evidence: taskContext.evidence, snapshot_digest: taskContext.freshness.snapshot_digest, allowed_files: taskContext.task.allowed_files, required_tests: taskContext.task.required_tests }, null, 2)}</pre></details>
                </div>}
                {taskContextError?.taskId === task.task_id && <p className="task-context__warning">{taskContextError.message}</p>}
              </div>)}
            </section>}
            {graph.data.pending_proposals.length > 0 && <section className="proposal-list">
              <h3>{t('pendingProposals')} · {graph.data.pending_proposals.length}</h3>
              {graph.data.pending_proposals.map((proposal) => <div key={proposal.proposal_id}>
                <strong>{proposal.rationale}</strong><code>{proposal.candidate_architecture_digest.slice(0, 12)}</code>
                <pre>{JSON.stringify(proposal.diff, null, 2)}</pre>
                <label><input type="checkbox" checked={reviewAcknowledged} onChange={(event) => setReviewAcknowledged(event.target.checked)} />{t('proposalAcknowledgement')}</label>
                <button disabled={!reviewAcknowledged} onClick={() => approveProposal(proposal.proposal_id, proposal.base_architecture_digest, proposal.candidate_architecture_digest).catch((reason) => setError(reason instanceof Error ? reason : new Error(String(reason))))}>{t('approveProposal')}</button>
              </div>)}
            </section>}
            {graph.data.latest_check && <section className="diagnostic-list">
              <h3>{t('checkDiagnostics')} · {graph.data.latest_check.diagnostics.length}</h3>
              {graph.data.latest_check.diagnostics.length === 0
                ? <p className="check-clean">{t('cleanCheck')}{graph.data.approval.protection === 'external_signature' ? ` ${t('externalCiSuffix')}` : ''}.</p>
                : graph.data.latest_check.diagnostics.slice(0, 8).map((item, index) => <div key={`${item.diagnostic_id}-${index}`}><strong>{item.diagnostic_id}</strong><p>{diagnosticMessage(language, item.diagnostic_id, item.message)}</p><code>{item.path}{item.line ? `:${item.line}` : ''}</code></div>)}
            </section>}
            {operation?.events && <section className="event-list">
              <h3>{t('recentEvents')} · {operation.event_count}</h3>
              {operation.events.slice(-8).reverse().map((event) => <div key={event.ingest_seq}><code>#{event.ingest_seq}</code><strong>{event.event_type}</strong><span>{event.module_id ?? event.flow_id ?? 'run'}</span></div>)}
            </section>}
          </div>
        ) : (
          <div className="inspector__content">
            <div className="inspector__heading"><span>{current.module.kind === 'composite' ? t('composite') : t('module')}</span><h2>{demoModuleLabel(language, projectId, current.module.id, current.module.name)}</h2><code>{current.module.id}</code></div><p className="purpose">{demoModulePurpose(language, projectId, current.module.id, current.module.purpose)}</p>
            <div className="status-grid"><div><small>{t('development')}</small><strong>{current.summary.implementation_status === 'not_ready' ? t('notReady') : current.summary.implementation_status === 'structural' ? t('structural') : current.summary.implementation_status === 'implemented' ? t('implemented') : t('historicalUnknown')}</strong></div><div><small>{t('verification')}</small><strong>{current.summary.verification_status}</strong></div><div><small>{t('run')}</small><strong>{current.summary.run_status}</strong></div></div>
            {current.runtime_summary && <section><h3>{t('runSummary')}</h3>{current.runtime_summary.error && <div className="runtime-error"><strong>{current.runtime_summary.error.error_type}</strong><p>{current.runtime_summary.error.message}</p></div>}<pre>{JSON.stringify({ inputs: current.runtime_summary.inputs, outputs: current.runtime_summary.outputs }, null, 2)}</pre></section>}
            <section><h3>{t('ports')}</h3>{current.module.ports.length ? current.module.ports.map((port) => <div className="port-row" key={port.id}><b className={`port-dir port-dir--${port.direction}`}>{port.direction}</b><strong>{port.id}</strong><span>{port.domain}</span></div>) : <p className="muted">{t('noPorts')}</p>}</section>
            {current.children.length > 0 && <section><h3>{t('children')}</h3><div className="chips">{current.children.map((child) => <button key={child} onClick={() => selectModule(child)}>{child}</button>)}</div></section>}
            <section><h3>{t('sourceBinding')}</h3>{current.module.binding ? <><div className="file-list">{current.module.binding.files.map((file) => <code key={file}>{file}</code>)}</div><p className="binding-note">{graph.data.historical ? t('historicalBinding') : `${t('matchedFiles')} ${current.summary.matched_files.length} ${language === 'en' ? 'files.' : '个文件。'}`}</p></> : <p className="muted">{t('noSourceBinding')}</p>}</section>
            {current.module.kind === 'leaf' && !graph.data.historical && <section className="repair-action"><h3>{t('localRepair')}</h3><p>{t('repairHint')}</p><button disabled={creatingTask || (!operation?.run_id && !graph.data.latest_check?.check_id)} onClick={() => prepareTask(current.module.id).catch((reason) => setError(reason instanceof Error ? reason : new Error(String(reason))))}>{creatingTask ? t('preparing') : t('createRepairTask')}</button>{!operation?.run_id && !graph.data.latest_check?.check_id && <small>{t('needRunOrCheck')}</small>}</section>}
          </div>)}
        {loadingModule && <div className="inspector__loading">{t('readingModule')}</div>}
      </aside>
    </main>
    {editor && <ArchitectureEditor projectId={projectId} language={language} initial={editor} onClose={() => setEditor(null)} onSaved={async () => { setEditor(null); setSelected(null); await loadGraph(runId) }} />}
  </div>
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
