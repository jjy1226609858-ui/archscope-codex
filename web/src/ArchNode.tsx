import { Handle, NodeProps, Position } from '@xyflow/react'
import { tr } from './i18n'
import type { Language } from './i18n'

type ArchNodeData = {
  label: string
  subtitle: string
  kind: 'leaf' | 'composite'
  implementation: string
  verification: string
  run: string
  expanded: boolean
  childCount: number
  language: Language
}

export function ArchNode({ data, selected }: NodeProps) {
  const node = data as unknown as ArchNodeData
  const language = node.language
  const implementationLabel = node.implementation === 'not_ready' ? tr(language, 'notReady') : node.implementation === 'structural' ? tr(language, 'structural') : tr(language, 'implemented')
  return (
    <div className={`arch-node ${node.kind} run--${node.run.toLowerCase()} ${selected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} className="flow-handle" />
      <div className="arch-node__eyebrow">
        <span>{tr(language, node.kind === 'composite' ? 'composite' : 'module')}</span>
        <span className={`readiness readiness--${node.implementation}`}>{implementationLabel}</span>
      </div>
      <strong>{node.label}</strong>
      <p>{node.subtitle}</p>
      <div className="arch-node__states">
        <span>{tr(language, 'verification')} {node.verification}</span>
        <span className={`run-chip run-chip--${node.run.toLowerCase()}`}>{tr(language, 'run')} {node.run}</span>
      </div>
      {node.kind === 'composite' && (
        <div className="arch-node__expand">{node.expanded ? tr(language, 'collapse') : `${tr(language, 'expand')} · ${node.childCount} ${tr(language, 'childModules')}`}</div>
      )}
      <Handle type="source" position={Position.Right} className="flow-handle" />
    </div>
  )
}
