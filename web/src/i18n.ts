export type Language = 'zh-CN' | 'en'

const zh = {
  language: '语言', brand: '架构视窗', currentProject: '当前项目', architectureVersion: '架构版本',
  current: '当前', historical: '历史', historicalReadOnly: '历史快照 · 只读',
  externalApproved: '外部签名已验证', localApproved: '本地人工批准', externalPending: '待外部签名批准', draft: '草案 · 未批准',
  starting: '正在启动', running: '运行中', cancelling: '正在取消', cancelled: '已取消', succeeded: '运行成功', failed: '运行失败', observationLost: '观测中断 · 结果未确认', notRun: '尚未运行',
  historicalCheck: '历史源码未重新核验', checkNotRun: '尚未检查', checkEligible: '可验收', checkPendingCi: '待外部 CI 签名', checkUnapproved: '未获有效批准',
  architectureReadFailed: '架构读取失败', runStatusReadFailed: '运行状态读取失败', moduleReadFailed: '模块读取失败', runStartFailed: '运行启动失败', cancelFailed: '取消失败', sourceCheckFailed: '源码检查失败', proposalApprovalFailed: '候选批准失败', noEvidence: '请先运行一次场景或源码边界检查，以形成可追溯证据', taskPrepareFailed: '任务准备失败', taskScopeApprovalFailed: '任务范围批准失败', reverifyFailed: '重新验收失败', resumeFailed: '恢复任务失败',
  fatalTitle: '无法打开架构视图', retry: '重试', loading: '正在读取架构事实…',
  realRun: '真实运行', historicalNoRun: '历史视图不启动新运行', probeOff: '探针已关闭 · 图上状态未观测', evidenceIncomplete: '事件证据不完整 · 图上不判定成功', cancelRun: '取消运行',
  actionIncomplete: '操作未完成', close: '关闭', closeError: '关闭错误提示',
  structureMap: '结构图', mapTitle: '系统模块与声明数据流', staticCheck: '静态检查', checking: '检查中…', checkSources: '检查源码边界',
  moduleInspector: '模块详情', chooseModule: '选择一个模块', chooseModuleHint: '单击节点查看职责、端口、源码绑定和本次真实运行摘要。双击组合模块可展开下一层。',
  repairTasks: '修复任务', allowedFiles: '允许修改', filesUnit: '个文件；必须通过', testsUnit: '项测试。架构文件与测试文件受保护。', exactScope: '查看精确范围', reviewScopeAcknowledgement: '我已核对证据、文件范围和必测项', approveTaskScope: '批准任务范围', waitingForCodex: '范围已批准，等待 Codex 原子领取。', claimTask: '使用 ArchScope 领取任务', inProgressBy: '正在由', codexSession: 'Codex 会话', noDoubleClaim: '处理；其他会话不能重复领取。', needsRealign: '现场已变化，旧任务不能继续领取；请重新核对架构与修改范围后创建新任务。', independentVerification: '独立验收：', architectureCheck: '架构检查', tests: '测试', externalEvidenceBlocked: '外部批准或 CI 证据尚未满足当前快照；证据到达后可重新验收。', reverify: '重新核验当前证据', checkingWorkspace: '正在核对现场…', resumeWorkspace: '核对 / 恢复任务现场', realignNeeded: '需重新对齐：', activeLease: '原会话租约仍有效，暂不可由另一会话接手。', claimable: '当前现场可供新会话领取；领取前仍会再次核对快照。', notClaimable: '已读取当前现场；此任务目前不可领取。', currentChanges: '当前改动：', none: '无', outOfScopeChanges: '范围外改动：', handoffPrefix: '交给新的 Codex 会话：继续 ArchScope 项目', handoffMiddle: '的任务', handoffSuffix: '，先调用任务恢复工具核对现场，再按批准范围领取。', currentEvidence: '查看当前证据与快照',
  pendingProposals: '待人工审阅候选', proposalAcknowledgement: '我已核对候选摘要和结构差异', approveProposal: '人工批准并更新正式架构', checkDiagnostics: '检查诊断', cleanCheck: '源码边界检查未发现违规；正式验收仍取决于有效批准', externalCiSuffix: '及当前代码/测试的外部 CI 签名', recentEvents: '最近事件',
  development: '开发', verification: '验证', run: '运行', notReady: '尚未实现', structural: '结构节点', implemented: '已有源码', historicalUnknown: '历史状态未知',
  runSummary: '本次运行摘要', ports: '接口端口', noPorts: '没有公开端口', children: '子模块', sourceBinding: '源码绑定', historicalBinding: '历史绑定记录；不与当前源码重新匹配。', matchedFiles: '实际匹配', noSourceBinding: '组合模块不直接绑定源码', localRepair: '局部修复', repairHint: '任务会绑定当前证据、源码快照、允许修改的文件和必测项；创建后仍需你审阅范围。', preparing: '正在准备…', createRepairTask: '创建修复任务', needRunOrCheck: '先运行场景或执行源码边界检查', readingModule: '正在读取模块…',
  module: '模块', composite: '组合模块', collapse: '双击收起', expand: '双击展开', childModules: '个子模块',
  taskObjectivePrefix: '修复「', taskObjectiveSuffix: '」的当前问题，同时保持公开接口和已批准架构不变',
  dataLanguageNote: '内置示例有中英名称；其他项目的名称、描述和原始诊断保持源文件语言。',
  targetPythonLaunchHint: '目标 Python 未启动（9009，且无模块事件）。请配置实际 Python 3.11+ 的绝对路径；Windows 应用执行别名不能运行此示例。',
  runtimeMissing: '没有找到可用的目标 Python 候选。运行示例前，请先安装或找到可信的 Python 3.11+，把命令中的 PYTHON_EXE_ABSOLUTE_PATH 替换成真实绝对路径，再在终端执行。',
  runtimeUnverified: '已发现目标 Python 候选，但尚未验证它能启动；点击运行场景时会先检查，不通过则不会创建运行记录。',
  runtimeRestart: '设置后新建 Codex 任务并重新打开工作台，让服务读取新的登记表。插件自带的运行程序不能替代目标项目的 Python。',
  editorOpen: '可视化编辑架构', editorLoading: '正在打开编辑器…', editorLoadFailed: '无法打开编辑器', editorRevisionChanged: '架构版本已变化，请刷新后重试',
  editorTitle: '可视化架构编辑', editorDraft: '仅编辑候选 · 不直接改写正式架构', editorClose: '关闭编辑器', editorNotice: '增删模块与端口、拖线建立数据流。拖动节点只调整当前画布布局，不写入 .arch。提交后仍需人工审阅差异并批准。',
  editorAddModule: '新增模块', editorName: '名称', editorKind: '类型', editorAdd: '添加模块', editorModule: '模块属性', editorPurpose: '职责', editorParent: '父模块', editorFiles: '源码匹配路径（每行一个）', editorPorts: '接口端口', editorPortId: '端口 ID', editorDirection: '方向', editorDomain: '数据域', editorAddPort: '添加端口', editorRemovePort: '删除端口', editorRemoveModule: '删除模块及其连接', editorFlow: '数据流', editorDescription: '说明', editorRemoveFlow: '删除数据流', editorConnect: '新建数据流', editorChoosePorts: '选择兼容端口', editorNoCompatiblePorts: '两端没有同一数据域的 out → in 端口。请先添加端口。', editorAddFlow: '添加数据流', editorCancelConnection: '取消连接', editorSubmit: '提交候选', editorRationale: '修改原因', editorSave: '生成待审候选', editorSaving: '正在校验并提交…', editorReviewHint: '提交不会修改正式 .arch；请在主界面查看差异并明确批准。序列化后的候选可能不保留原 YAML 注释。', editorSaveFailed: '候选提交失败', editorNeedRationale: '请先修改架构并填写修改原因', editorInvalidModuleId: '模块 ID 须以字母开头，仅含字母、数字、下划线或连字符，且不可重复', editorInvalidPortId: '端口 ID 无效或重复', editorRemoveChildrenFirst: '请先移除该组合模块的子模块',
} as const

const en: Record<keyof typeof zh, string> = {
  language: 'Language', brand: 'Architecture Workbench', currentProject: 'CURRENT PROJECT', architectureVersion: 'Architecture revision',
  current: 'Current', historical: 'History', historicalReadOnly: 'Historical snapshot · read-only',
  externalApproved: 'External signature verified', localApproved: 'Approved locally', externalPending: 'Awaiting external signature', draft: 'Draft · unapproved',
  starting: 'Starting', running: 'Running', cancelling: 'Cancelling', cancelled: 'Cancelled', succeeded: 'Run succeeded', failed: 'Run failed', observationLost: 'Observation lost · result unknown', notRun: 'Not run',
  historicalCheck: 'Historical source not rechecked', checkNotRun: 'Not checked', checkEligible: 'eligible', checkPendingCi: 'awaiting external CI signature', checkUnapproved: 'not validly approved',
  architectureReadFailed: 'Could not read architecture', runStatusReadFailed: 'Could not read run status', moduleReadFailed: 'Could not read module', runStartFailed: 'Could not start run', cancelFailed: 'Could not cancel run', sourceCheckFailed: 'Source check failed', proposalApprovalFailed: 'Could not approve proposal', noEvidence: 'Run a scenario or source-boundary check first to create traceable evidence', taskPrepareFailed: 'Could not prepare task', taskScopeApprovalFailed: 'Could not approve task scope', reverifyFailed: 'Could not reverify task', resumeFailed: 'Could not resume task',
  fatalTitle: 'Could not open architecture view', retry: 'Retry', loading: 'Loading architecture facts…',
  realRun: 'REAL RUN', historicalNoRun: 'Historical view cannot start a new run', probeOff: 'Probe off · graph status unobserved', evidenceIncomplete: 'Event evidence incomplete · success not inferred', cancelRun: 'Cancel run',
  actionIncomplete: 'Action incomplete', close: 'Close', closeError: 'Close error message',
  structureMap: 'STRUCTURE MAP', mapTitle: 'System modules and declared data flows', staticCheck: 'STATIC CHECK', checking: 'Checking…', checkSources: 'Check source boundaries',
  moduleInspector: 'MODULE INSPECTOR', chooseModule: 'Select a module', chooseModuleHint: 'Click a node to inspect its role, ports, source binding and run summary. Double-click a composite to expand it.',
  repairTasks: 'Repair tasks', allowedFiles: 'May change', filesUnit: 'files; must pass', testsUnit: 'tests. Architecture and test files are protected.', exactScope: 'Show exact scope', reviewScopeAcknowledgement: 'I reviewed the evidence, file scope and required tests', approveTaskScope: 'Approve task scope', waitingForCodex: 'Scope approved; waiting for Codex to claim atomically.', claimTask: 'Use ArchScope to claim task', inProgressBy: 'In progress by', codexSession: 'a Codex session', noDoubleClaim: '; other sessions cannot claim it again.', needsRealign: 'Workspace changed. This task cannot be claimed until its architecture and scope are reviewed again.', independentVerification: 'Independent verification:', architectureCheck: 'architecture check', tests: 'tests', externalEvidenceBlocked: 'External approval or CI evidence does not match the current snapshot; reverify when evidence arrives.', reverify: 'Reverify current evidence', checkingWorkspace: 'Checking workspace…', resumeWorkspace: 'Check / resume task context', realignNeeded: 'Realignment needed:', activeLease: 'The original session lease is still active; another session cannot take over.', claimable: 'A new session can claim this workspace; the snapshot will be checked again.', notClaimable: 'Current workspace read; this task is not claimable now.', currentChanges: 'Current changes:', none: 'none', outOfScopeChanges: 'Out-of-scope changes:', handoffPrefix: 'For a new Codex session: continue ArchScope project', handoffMiddle: 'task', handoffSuffix: '; resume the task to check the workspace, then claim within the approved scope.', currentEvidence: 'Show current evidence and snapshot',
  pendingProposals: 'Proposals awaiting human review', proposalAcknowledgement: 'I reviewed the candidate digest and structural diff', approveProposal: 'Approve and update the formal architecture', checkDiagnostics: 'Check diagnostics', cleanCheck: 'The source-boundary check found no violations; formal acceptance still requires valid approval', externalCiSuffix: 'and an external CI signature for current code/tests', recentEvents: 'Recent events',
  development: 'Development', verification: 'Verification', run: 'Run', notReady: 'Not implemented', structural: 'Structural node', implemented: 'Source present', historicalUnknown: 'Historical state unknown',
  runSummary: 'Run summary', ports: 'Interface ports', noPorts: 'No public ports', children: 'Child modules', sourceBinding: 'Source binding', historicalBinding: 'Historical binding; not rematched against current source.', matchedFiles: 'Matched', noSourceBinding: 'Composite has no direct source binding', localRepair: 'Local repair', repairHint: 'The task binds evidence, source snapshot, allowed files and required tests; you must review its scope after creation.', preparing: 'Preparing…', createRepairTask: 'Create repair task', needRunOrCheck: 'Run a scenario or source-boundary check first', readingModule: 'Loading module…',
  module: 'MODULE', composite: 'COMPOSITE', collapse: 'Double-click to collapse', expand: 'Double-click to expand', childModules: 'child modules',
  taskObjectivePrefix: 'Fix the current issue in “', taskObjectiveSuffix: '” while preserving public interfaces and the approved architecture',
  dataLanguageNote: 'The bundled demo has localized labels; other projects retain their authored names, descriptions, and diagnostics.',
  targetPythonLaunchHint: 'Target Python did not start (9009; no module events). Configure the absolute path to a real Python 3.11+ interpreter; the Windows app execution alias cannot run this demo.',
  runtimeMissing: 'No target Python candidate was found. Before running the demo, install or locate a trusted Python 3.11+, replace PYTHON_EXE_ABSOLUTE_PATH with its real absolute path, and run this terminal command.',
  runtimeUnverified: 'A target Python candidate was found but has not been verified. Starting a scenario checks it first; a failed check creates no run record.',
  runtimeRestart: 'Start a new Codex task and reopen the workbench after setting it so the service reloads the registry. The bundled ArchScope executable is not a target-project Python interpreter.',
  editorOpen: 'Edit architecture', editorLoading: 'Opening editor…', editorLoadFailed: 'Could not open editor', editorRevisionChanged: 'Architecture changed; refresh and try again',
  editorTitle: 'Visual architecture editor', editorDraft: 'Candidate only · formal architecture stays unchanged', editorClose: 'Close editor', editorNotice: 'Add or remove modules and ports, then drag a connection to declare a flow. Moving nodes changes only this view, not .arch. Submit for human diff review and approval.',
  editorAddModule: 'Add module', editorName: 'Name', editorKind: 'Kind', editorAdd: 'Add module', editorModule: 'Module properties', editorPurpose: 'Purpose', editorParent: 'Parent module', editorFiles: 'Source patterns (one per line)', editorPorts: 'Ports', editorPortId: 'Port ID', editorDirection: 'Direction', editorDomain: 'Domain', editorAddPort: 'Add port', editorRemovePort: 'Remove port', editorRemoveModule: 'Remove module and its flows', editorFlow: 'Flow', editorDescription: 'Description', editorRemoveFlow: 'Remove flow', editorConnect: 'New flow', editorChoosePorts: 'Choose compatible ports', editorNoCompatiblePorts: 'No matching out → in ports with the same domain. Add ports first.', editorAddFlow: 'Add flow', editorCancelConnection: 'Cancel connection', editorSubmit: 'Submit candidate', editorRationale: 'Reason for change', editorSave: 'Create pending proposal', editorSaving: 'Validating and submitting…', editorReviewHint: 'Submitting does not change formal .arch; review the diff in the workbench and explicitly approve. YAML comments may not be preserved in the generated candidate.', editorSaveFailed: 'Could not submit proposal', editorNeedRationale: 'Change the architecture and provide a reason', editorInvalidModuleId: 'Module ID must start with a letter, use letters, digits, underscores or hyphens, and be unique', editorInvalidPortId: 'Port ID is invalid or duplicate', editorRemoveChildrenFirst: 'Remove child modules first',
}

export type MessageKey = keyof typeof zh

export function tr(language: Language, key: MessageKey): string {
  return language === 'en' ? en[key] : zh[key]
}

// The API uses stable diagnostic IDs and English detail text. Keep that detail
// available, but give Chinese-mode users an actionable summary first.
const diagnosticZh: Record<string, string> = {
  HTTP_ORIGIN_REJECTED: '工作台拒绝了来自其他网页的写操作。请从本地 ArchScope 页面重试。',
  HTTP_SESSION_REQUIRED: '工作台会话已失效。请刷新页面后重试。',
  TARGET_PYTHON_NOT_FOUND: '目标 Python 不可用。请配置实际 Python 3.11+ 解释器的绝对路径。',
  RUN_LAUNCH_FAILED: '目标程序未能启动。请检查解释器和运行档案。',
  RUN_PROFILE_NOT_FOUND: '运行档案不存在或未获准。',
  RUN_PROFILES_INVALID: '运行档案配置无效。',
  RUN_SCENARIO_UNREADABLE: '场景文件无法读取。',
  RUN_SCENARIO_TOO_LARGE: '场景文件超过大小限制。',
  RUN_REVISION_MISMATCH: '运行记录与当前架构版本不匹配。',
  RUN_RESULT_MISSING: '目标未写出结果，不能确认运行成败。',
  RUN_OWNER_LOST: '当前会话不再拥有该运行，结果未确认。',
  REVISION_CONFLICT: '架构版本已变化，请刷新并重新核对。',
  CODE_REVISION_CONFLICT: '代码快照已变化，请刷新并重新核对。',
  IDEMPOTENCY_CONFLICT: '同一请求标识已用于不同内容。',
  CANDIDATE_INVALID: '架构候选无效。',
  CANDIDATE_DIGEST_CONFLICT: '候选内容与审阅时的摘要不一致。',
  REVIEW_CONFIRMATION_REQUIRED: '必须在本地审阅界面明确确认候选。',
  PROPOSAL_NOT_REVIEWABLE: '此候选目前不能批准。',
  TASK_SCOPE_CONFIRMATION_REQUIRED: '必须在本地审阅界面明确确认任务范围。',
  TASK_STALE: '任务依据的工作区已变化，需要重新对齐。',
  TASK_RESUME_REQUIRED: '请先恢复任务上下文并核对当前快照。',
  TASK_SNAPSHOT_CONFLICT: '恢复任务后工作区又发生了变化。',
  APPROVAL_REQUIRED: '任务范围尚未批准或当前不可领取。',
  TASK_ALREADY_CLAIMED: '任务已由其他会话领取。',
  EVIDENCE_REQUIRED: '需要可追溯证据才能创建任务。',
  EVIDENCE_NOT_FOUND: '找不到所需证据。',
  SOURCE_ROOT_MISSING: '源码根目录不存在。',
  SOURCE_PATH_ESCAPE: '源码路径越出了项目根目录。',
  BINDING_EMPTY: '源码绑定没有匹配任何 Python 文件。',
  UNOWNED_SOURCE: '源码文件没有模块归属。',
  FILE_OWNERSHIP_CONFLICT: '源码文件被多个模块同时归属。',
  PYTHON_PARSE_ERROR: 'Python 源码无法静态解析。',
  ENTRY_MODULE_MISSING: '公开入口模块不存在。',
  ENTRY_SYMBOL_MISSING: '公开入口符号不存在。',
  DEPENDENCY_DENIED: '模块导入违反依赖规则。',
  PRIVATE_IMPORT: '模块导入了其他模块的非公开实现。',
  UNVERIFIED_DYNAMIC_IMPORT: '动态导入的目标无法由静态检查确认。',
}

export function diagnosticMessage(language: Language, id: string | undefined, detail: string): string {
  if (language === 'en' || !id) return detail
  const summary = diagnosticZh[id]
  const technicalDetail = detail.startsWith(`${id}: `) ? detail.slice(id.length + 2) : detail
  return summary ? `${summary}（${id}：${technicalDetail}）` : `请求未完成（${id}）：${technicalDetail}`
}

export function initialLanguage(): Language {
  try {
    const saved = window.localStorage.getItem('archscope.language')
    if (saved === 'en' || saved === 'zh-CN') return saved
  } catch { /* Storage may be disabled. */ }
  return 'en'
}

export function rememberLanguage(language: Language): void {
  document.documentElement.lang = language
  document.title = language === 'en' ? 'ArchScope Architecture Workbench' : 'ArchScope 架构视窗'
  try { window.localStorage.setItem('archscope.language', language) } catch { /* Keep the in-memory selection. */ }
}

export function demoProfileLabel(language: Language, projectId: string, profileId: string, original: string): string {
  if (projectId !== 'mini_planner') return original
  const labels = language === 'en'
    ? { 'demo-normal': 'Normal plan', 'demo-bad-input': 'Invalid input', 'demo-search-error': 'Search error', 'demo-slow': 'Slow run (cancel)' }
    : { 'demo-normal': '正常规划', 'demo-bad-input': '输入异常', 'demo-search-error': '搜索异常', 'demo-slow': '可取消慢运行' }
  return (labels as Record<string, string>)[profileId] ?? original
}

const demoZhModules: Record<string, [string, string]> = {
  app: ['组合入口', '用普通 Python 组织调用，显式记录主要数据传递，不使用图调度器。'],
  contracts: ['领域对象', '提供共享领域对象定义；不引用业务实现。'],
  data: ['数据输入', '读取测试场景并验证必要输入。'],
  planning: ['规划子系统', '封装搜索与碰撞检查；展开图不改变语义。'],
  search: ['路径搜索', '在给定场景中搜索路径，通过公共接口获取碰撞判断。'],
  collision: ['碰撞检查', '判断候选位置的可通行性；内部几何工具不公开。'],
  reporter: ['结果输出', '只读取规划结果生成摘要，不直接依赖碰撞检查内部实现。'],
}

export function demoProjectLabel(language: Language, projectId: string, original: string): string {
  return language === 'zh-CN' && projectId === 'mini_planner' ? '网格路径规划验证项目' : original
}

export function demoModuleLabel(language: Language, projectId: string, moduleId: string, original: string): string {
  return language === 'zh-CN' && projectId === 'mini_planner' ? demoZhModules[moduleId]?.[0] ?? original : original
}

export function demoModulePurpose(language: Language, projectId: string, moduleId: string, original: string): string {
  return language === 'zh-CN' && projectId === 'mini_planner' ? demoZhModules[moduleId]?.[1] ?? original : original
}
