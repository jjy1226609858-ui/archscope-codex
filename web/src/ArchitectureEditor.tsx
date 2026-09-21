import { useMemo, useState } from 'react'
import { Background, Controls, MarkerType, MiniMap, ReactFlow } from '@xyflow/react'
import type { Connection, Edge, Node } from '@xyflow/react'
import { ArchNode } from './ArchNode'
import { apiFetch } from './apiFetch'
import { diagnosticMessage, tr } from './i18n'
import type { Language } from './i18n'

type Port = { id: string; direction: 'in' | 'out'; domain: string; description?: string; delegate?: { module: string; port: string } }
type Module = { id: string; name: string; purpose: string; kind: 'leaf' | 'composite'; parent?: string; ports: Port[]; binding?: { files: string[]; public_imports: string[]; entries: { id: string; symbol: string }[] } }
type Flow = { id: string; from: { module: string; port: string }; to: { module: string; port: string }; transport: 'in_process'; description: string }
type EditorEnvelope = { architecture_digest: string; data: { modules: Module[]; flows: Flow[]; domains: { id: string; name: string }[] } }
type Props = { projectId: string; language: Language; initial: EditorEnvelope; onClose: () => void; onSaved: () => Promise<void> }
const nodeTypes = { arch: ArchNode }
const validId = /^[A-Za-z][A-Za-z0-9_-]*$/

export function ArchitectureEditor({ projectId, language, initial, onClose, onSaved }: Props) {
  const t = (key: Parameters<typeof tr>[1]) => tr(language, key)
  const [modules, setModules] = useState<Module[]>(() => structuredClone(initial.data.modules))
  const [flows, setFlows] = useState<Flow[]>(() => structuredClone(initial.data.flows))
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({})
  const [selectedModule, setSelectedModule] = useState<string | null>(null)
  const [selectedFlow, setSelectedFlow] = useState<string | null>(null)
  const [connection, setConnection] = useState<{ source: string; target: string } | null>(null)
  const [portPair, setPortPair] = useState('')
  const [newId, setNewId] = useState('')
  const [newName, setNewName] = useState('')
  const [newKind, setNewKind] = useState<'leaf' | 'composite'>('leaf')
  const [newPortId, setNewPortId] = useState('')
  const [newPortDirection, setNewPortDirection] = useState<'in' | 'out'>('in')
  const [newPortDomain, setNewPortDomain] = useState(initial.data.domains[0]?.id ?? '')
  const [rationale, setRationale] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  const selected = modules.find((item) => item.id === selectedModule)
  const selectedEdge = flows.find((item) => item.id === selectedFlow)
  const nodes = useMemo<Node[]>(() => modules.map((module, index) => ({
    id: module.id, type: 'arch', position: positions[module.id] ?? { x: 40 + (index % 3) * 360, y: 40 + Math.floor(index / 3) * 210 },
    data: { label: module.name, subtitle: module.purpose, kind: module.kind, implementation: 'structural', verification: 'draft', run: 'draft', expanded: false, childCount: modules.filter((item) => item.parent === module.id).length, language },
  })), [modules, positions, language])
  const edges = useMemo<Edge[]>(() => flows.map((flow) => ({
    id: flow.id, source: flow.from.module, target: flow.to.module, label: `${flow.from.port} → ${flow.to.port}`,
    markerEnd: { type: MarkerType.ArrowClosed, color: '#8291ff' }, style: { stroke: '#8291ff', strokeWidth: 1.7 },
    labelStyle: { fill: '#aeb8d7', fontSize: 11 }, labelBgStyle: { fill: '#101629', fillOpacity: 0.9 },
  })), [flows])
  const compatiblePairs = useMemo(() => {
    if (!connection) return []
    const source = modules.find((item) => item.id === connection.source)
    const target = modules.find((item) => item.id === connection.target)
    return (source?.ports ?? []).filter((port) => port.direction === 'out').flatMap((out) =>
      (target?.ports ?? []).filter((input) => input.direction === 'in' && input.domain === out.domain)
        .map((input) => ({ out: out.id, input: input.id, domain: out.domain })))
  }, [connection, modules])

  function changeModule(next: Module) {
    setModules((current) => current.map((item) => item.id === next.id ? next : item))
    setDirty(true)
  }

  function addModule() {
    const id = newId.trim()
    if (!validId.test(id) || modules.some((item) => item.id === id)) { setError(t('editorInvalidModuleId')); return }
    const module: Module = {
      id, name: newName.trim() || id, purpose: language === 'en' ? 'Describe this module' : '请填写模块职责', kind: newKind, ports: [],
      ...(newKind === 'leaf' ? { binding: { files: [`src/${id}/**`], public_imports: [], entries: [] } } : {}),
    }
    setModules((current) => [...current, module]); setSelectedModule(id); setSelectedFlow(null)
    setNewId(''); setNewName(''); setDirty(true); setError(null)
  }

  function removeModule(module: Module) {
    if (modules.some((item) => item.parent === module.id)) { setError(t('editorRemoveChildrenFirst')); return }
    setModules((current) => current.filter((item) => item.id !== module.id))
    setFlows((current) => current.filter((item) => item.from.module !== module.id && item.to.module !== module.id))
    setSelectedModule(null); setDirty(true); setError(null)
  }

  function addPort() {
    if (!selected || !validId.test(newPortId.trim()) || selected.ports.some((item) => item.id === newPortId.trim())) { setError(t('editorInvalidPortId')); return }
    changeModule({ ...selected, ports: [...selected.ports, { id: newPortId.trim(), direction: newPortDirection, domain: newPortDomain }] })
    setNewPortId(''); setError(null)
  }

  function removePort(portId: string) {
    if (!selected) return
    changeModule({ ...selected, ports: selected.ports.filter((item) => item.id !== portId) })
    setFlows((current) => current.filter((item) => !(item.from.module === selected.id && item.from.port === portId) && !(item.to.module === selected.id && item.to.port === portId)))
  }

  function beginConnect(candidate: Connection) {
    if (!candidate.source || !candidate.target) return
    setConnection({ source: candidate.source, target: candidate.target }); setPortPair(''); setError(null)
  }

  function addFlow() {
    if (!connection) return
    const pair = compatiblePairs[Number(portPair)]
    if (!pair) { setError(t('editorChoosePorts')); return }
    const baseId = `${connection.source}_${pair.out}_to_${connection.target}_${pair.input}`
    let id = baseId; let number = 2
    while (flows.some((item) => item.id === id)) id = `${baseId}_${number++}`
    setFlows((current) => [...current, { id, from: { module: connection.source, port: pair.out }, to: { module: connection.target, port: pair.input }, transport: 'in_process', description: `${connection.source}.${pair.out} → ${connection.target}.${pair.input}` }])
    setConnection(null); setDirty(true); setError(null)
  }

  async function save() {
    if (!dirty || !rationale.trim()) { setError(t('editorNeedRationale')); return }
    setSaving(true); setError(null)
    try {
      const response = await apiFetch('/api/visual-proposals', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        project_id: projectId, modules, flows, expected_architecture_digest: initial.architecture_digest,
        rationale: rationale.trim(), idempotency_key: `visual-${crypto.randomUUID()}`,
      }) })
      if (!response.ok) {
        const payload = await response.json()
        const diagnostic = payload?.detail?.diagnostics?.[0]
        throw new Error(typeof diagnostic?.message === 'string'
          ? diagnosticMessage(language, diagnostic.diagnostic_id, diagnostic.message)
          : `${t('editorSaveFailed')} (${response.status})`)
      }
      await onSaved()
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setSaving(false) }
  }

  return <div className="architecture-editor" role="dialog" aria-modal="true" aria-label={t('editorTitle')}>
    <header className="architecture-editor__header"><div><small>{t('editorDraft')}</small><h2>{t('editorTitle')}</h2><code>{initial.architecture_digest.slice(0, 12)}</code></div><button onClick={onClose}>{t('editorClose')}</button></header>
    <div className="architecture-editor__notice">{t('editorNotice')}</div>
    {error && <div className="architecture-editor__error" role="alert">{error}</div>}
    <div className="architecture-editor__body">
      <div className="architecture-editor__canvas"><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodeClick={(_, node) => { setSelectedModule(node.id); setSelectedFlow(null) }} onEdgeClick={(_, edge) => { setSelectedFlow(edge.id); setSelectedModule(null) }} onNodeDragStop={(_, node) => setPositions((current) => ({ ...current, [node.id]: node.position }))} onConnect={beginConnect} nodesConnectable fitView minZoom={0.3} maxZoom={1.5} proOptions={{ hideAttribution: true }}><Background color="#313a59" gap={28} size={1} /><Controls /><MiniMap /></ReactFlow></div>
      <aside className="architecture-editor__side">
        <section><h3>{t('editorAddModule')}</h3><label>ID<input value={newId} onChange={(event) => setNewId(event.target.value)} placeholder="my_module" /></label><label>{t('editorName')}<input value={newName} onChange={(event) => setNewName(event.target.value)} /></label><label>{t('editorKind')}<select value={newKind} onChange={(event) => setNewKind(event.target.value as 'leaf' | 'composite')}><option value="leaf">leaf</option><option value="composite">composite</option></select></label><button onClick={addModule}>{t('editorAdd')}</button></section>
        {selected && <section><h3>{t('editorModule')} · {selected.id}</h3><label>{t('editorName')}<input value={selected.name} onChange={(event) => changeModule({ ...selected, name: event.target.value })} /></label><label>{t('editorPurpose')}<textarea value={selected.purpose} onChange={(event) => changeModule({ ...selected, purpose: event.target.value })} /></label><label>{t('editorParent')}<select value={selected.parent ?? ''} onChange={(event) => { const next = { ...selected }; if (event.target.value) next.parent = event.target.value; else delete next.parent; changeModule(next) }}><option value="">—</option>{modules.filter((item) => item.kind === 'composite' && item.id !== selected.id).map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}</select></label>{selected.kind === 'leaf' && <label>{t('editorFiles')}<textarea value={selected.binding?.files.join('\n') ?? ''} onChange={(event) => changeModule({ ...selected, binding: { files: event.target.value.split('\n').map((line) => line.trim()).filter(Boolean), public_imports: selected.binding?.public_imports ?? [], entries: selected.binding?.entries ?? [] } })} /></label>}<h4>{t('editorPorts')}</h4>{selected.ports.map((port) => <div className="architecture-editor__port" key={port.id}><span>{port.direction} · {port.id} · {port.domain}</span><button onClick={() => removePort(port.id)} aria-label={`${t('editorRemovePort')} ${port.id}`}>×</button></div>)}<label>{t('editorPortId')}<input value={newPortId} onChange={(event) => setNewPortId(event.target.value)} /></label><div className="architecture-editor__row"><select aria-label={t('editorDirection')} value={newPortDirection} onChange={(event) => setNewPortDirection(event.target.value as 'in' | 'out')}><option value="in">in</option><option value="out">out</option></select><select aria-label={t('editorDomain')} value={newPortDomain} onChange={(event) => setNewPortDomain(event.target.value)}>{initial.data.domains.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}</select><button onClick={addPort}>{t('editorAddPort')}</button></div><button className="architecture-editor__danger" onClick={() => removeModule(selected)}>{t('editorRemoveModule')}</button></section>}
        {selectedEdge && <section><h3>{t('editorFlow')} · {selectedEdge.id}</h3><p>{selectedEdge.from.module}.{selectedEdge.from.port} → {selectedEdge.to.module}.{selectedEdge.to.port}</p><label>{t('editorDescription')}<textarea value={selectedEdge.description} onChange={(event) => { setFlows((current) => current.map((item) => item.id === selectedEdge.id ? { ...item, description: event.target.value } : item)); setDirty(true) }} /></label><button className="architecture-editor__danger" onClick={() => { setFlows((current) => current.filter((item) => item.id !== selectedEdge.id)); setSelectedFlow(null); setDirty(true) }}>{t('editorRemoveFlow')}</button></section>}
        {connection && <section><h3>{t('editorConnect')} · {connection.source} → {connection.target}</h3>{compatiblePairs.length ? <><label>{t('editorChoosePorts')}<select value={portPair} onChange={(event) => setPortPair(event.target.value)}><option value="">—</option>{compatiblePairs.map((pair, index) => <option key={index} value={index}>{pair.out} → {pair.input} ({pair.domain})</option>)}</select></label><button onClick={addFlow}>{t('editorAddFlow')}</button></> : <p>{t('editorNoCompatiblePorts')}</p>}<button onClick={() => setConnection(null)}>{t('editorCancelConnection')}</button></section>}
        <section><h3>{t('editorSubmit')}</h3><label>{t('editorRationale')}<textarea value={rationale} onChange={(event) => setRationale(event.target.value)} /></label><button disabled={saving || !dirty} onClick={save}>{saving ? t('editorSaving') : t('editorSave')}</button><p>{t('editorReviewHint')}</p></section>
      </aside>
    </div>
  </div>
}
