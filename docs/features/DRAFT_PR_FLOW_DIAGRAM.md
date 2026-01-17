# Draft PR Orchestrator Flow Diagram

## Complete Pipeline Flow

```mermaid
flowchart TD
    Start([User: Create Draft PR Job]) --> CreateAPI[POST /draft-pr/create]
    CreateAPI --> CheckDuplicate{Duplicate Job?}
    CheckDuplicate -->|Yes| Error409[409 Conflict]
    CheckDuplicate -->|No| CreateJob[Create Job Status<br/>job_id, stage=CREATED]
    CreateJob --> QueueJob[Queue ARQ Worker Job]
    QueueJob --> WorkerStart[Worker: process_draft_pr_worker]
    
    WorkerStart --> FetchJIRA[Fetch Story from JIRA<br/>summary, description]
    FetchJIRA --> InitPipeline[Initialize Pipeline Services<br/>PlanGenerator, WorkspaceManager,<br/>ArtifactStore, OpenCodeRunner]
    
    InitPipeline --> Stage1[STAGE 1: PLANNING]
    Stage1 --> CreateWorkspace[Create Workspace<br/>Clone Repositories]
    CreateWorkspace --> CheckCancel1{Cancelled?}
    CheckCancel1 -->|Yes| Cleanup1[Cleanup Workspace]
    Cleanup1 --> CancelEnd([Job Cancelled])
    
    CheckCancel1 -->|No| GeneratePlan[Generate Plan v1<br/>PlanGenerator.generate_plan]
    GeneratePlan --> StorePlan1[Store plan_v1 Artifact]
    StorePlan1 --> CheckCancel2{Cancelled?}
    CheckCancel2 -->|Yes| Cleanup2[Cleanup Workspace]
    Cleanup2 --> CancelEnd
    
    CheckCancel2 -->|No| CheckMode{Mode?}
    
    CheckMode -->|YOLO| YOLOEvaluate[YOLO Policy Evaluation]
    YOLOEvaluate --> YOLOCompliant{Compliant?}
    YOLOCompliant -->|Yes| AutoApprove[Auto-Approve Plan]
    AutoApprove --> Stage3[STAGE 3: APPLY]
    YOLOCompliant -->|No| Stage2[STAGE 2: WAITING_FOR_APPROVAL]
    
    CheckMode -->|Normal| Stage2
    
    Stage2 --> WaitApproval[Job Paused<br/>Waiting for User Approval]
    WaitApproval --> UserReview[User Reviews Plan<br/>GET /draft-pr/jobs/job_id/plan]
    UserReview --> UserDecision{User Decision?}
    
    UserDecision -->|Revise| RevisePlan[POST /draft-pr/jobs/job_id/revise-plan]
    RevisePlan --> GenerateRevPlan[PlanGenerator.revise_plan<br/>Generate plan_v2, v3, ...]
    GenerateRevPlan --> StoreRevPlan[Store plan_vN Artifact]
    StoreRevPlan --> InvalidateApproval[Invalidate Previous Approval]
    InvalidateApproval --> WaitApproval
    
    UserDecision -->|Approve| ApproveAPI[POST /draft-pr/jobs/job_id/approve]
    ApproveAPI --> CheckCancel3{Cancelled?}
    CheckCancel3 -->|Yes| ErrorCancel[400: Job Cancelled]
    CheckCancel3 -->|No| AcquireLock[Acquire Redis Lock<br/>Prevent Concurrent Approval]
    AcquireLock --> VerifyPlanHash[Verify Plan Hash<br/>Must Match Latest Plan]
    VerifyPlanHash --> StoreApproval[Store Approval Artifact]
    StoreApproval --> UpdateJob[Update Job Status<br/>approved_plan_hash, stage=APPLYING]
    UpdateJob --> ReleaseLock[Release Redis Lock]
    ReleaseLock --> ContinuePipeline[continue_pipeline_after_approval]
    
    ContinuePipeline --> Stage3
    
    Stage3 --> CheckCancel4{Cancelled?}
    CheckCancel4 -->|Yes| Cleanup3[Cleanup Workspace]
    Cleanup3 --> CancelEnd
    
    CheckCancel4 -->|No| ApplyCode[CodeApplier.apply_plan<br/>Execute OpenCode Container]
    ApplyCode --> GitCheckpoint[Create Git Checkpoint<br/>Before Changes]
    GitCheckpoint --> ExecuteOpenCode[Run OpenCode<br/>Apply Code Changes]
    ExecuteOpenCode --> VerifyPlanApply{Plan-Apply Guard<br/>Changes Match Plan?}
    VerifyPlanApply -->|No| RollbackGit[Rollback to Checkpoint]
    RollbackGit --> ErrorPlanMismatch[Error: Plan Mismatch]
    
    VerifyPlanApply -->|Yes| StoreDiff[Store Git Diff Artifact]
    StoreDiff --> CheckCancel5{Cancelled?}
    CheckCancel5 -->|Yes| Cleanup4[Cleanup Workspace]
    Cleanup4 --> CancelEnd
    
    CheckCancel5 -->|No| Stage4[STAGE 4: VERIFY]
    
    Stage4 --> CheckCancel6{Cancelled?}
    CheckCancel6 -->|Yes| Cleanup5[Cleanup Workspace]
    Cleanup5 --> CancelEnd
    
    CheckCancel6 -->|No| RunTests[Verifier.verify<br/>Run Test Command]
    RunTests --> RunLint[Run Lint Command]
    RunLint --> RunBuild[Run Build Command]
    RunBuild --> VerifyPass{All Passed?}
    VerifyPass -->|No| StoreLogs[Store Validation Logs]
    StoreLogs --> ErrorVerify[Error: Verification Failed]
    
    VerifyPass -->|Yes| StoreLogs2[Store Validation Logs]
    StoreLogs2 --> CheckCancel7{Cancelled?}
    CheckCancel7 -->|Yes| Cleanup6[Cleanup Workspace]
    CheckCancel6 --> CancelEnd
    
    CheckCancel7 -->|No| Stage5[STAGE 5: PACKAGE]
    
    Stage5 --> PackageService[PackageService.package<br/>Generate PR Metadata]
    PackageService --> StorePRMeta[Store PR Metadata Artifact]
    StorePRMeta --> Stage6[STAGE 6: DRAFT_PR]
    
    Stage6 --> DetectDefaultBranch[Detect Default Branch<br/>main/master/develop]
    DetectDefaultBranch --> CreateBranch[Create Branch<br/>augment/ticket-key-hash]
    CreateBranch --> BranchExists{Branch Exists?}
    BranchExists -->|Yes| RetryBranch[Retry with Suffix<br/>-1, -2, ... up to 5]
    RetryBranch --> BranchExists
    
    BranchExists -->|No| PushBranch[Push Branch to Bitbucket]
    PushBranch --> CreatePR[Create Draft PR<br/>Link to Story]
    CreatePR --> PRSuccess{PR Created?}
    PRSuccess -->|Partial| StorePartial[Store Partial Failure<br/>Branch exists, PR failed]
    StorePartial --> ErrorPartial[Error: Partial Failure]
    
    PRSuccess -->|Yes| StorePRMeta2[Update PR Metadata<br/>pr_id, pr_url]
    StorePRMeta2 --> Stage7[STAGE 7: COMPLETED]
    
    Stage7 --> CleanupWorkspace[Cleanup Workspace]
    CleanupWorkspace --> UpdateJobComplete[Update Job Status<br/>status=completed, PR URL]
    UpdateJobComplete --> Success([Success: Draft PR Created])
    
    Error409 --> End1([End])
    ErrorCancel --> End2([End])
    ErrorPlanMismatch --> End3([End])
    ErrorVerify --> End4([End])
    ErrorPartial --> End5([End])
    CancelEnd --> End6([End])
    
    style Start fill:#e1f5ff
    style Success fill:#d4edda
    style Stage1 fill:#fff3cd
    style Stage2 fill:#fff3cd
    style Stage3 fill:#fff3cd
    style Stage4 fill:#fff3cd
    style Stage5 fill:#fff3cd
    style Stage6 fill:#fff3cd
    style Stage7 fill:#d4edda
    style Error409 fill:#f8d7da
    style ErrorCancel fill:#f8d7da
    style ErrorPlanMismatch fill:#f8d7da
    style ErrorVerify fill:#f8d7da
    style ErrorPartial fill:#f8d7da
    style CancelEnd fill:#f8d7da
    style WaitApproval fill:#cfe2ff
    style YOLOEvaluate fill:#e7f3ff
    style AutoApprove fill:#d1e7dd
```

## Plan Revision Flow

```mermaid
flowchart TD
    Start([User: Review Plan]) --> GetPlan[GET /draft-pr/jobs/job_id/plan]
    GetPlan --> ViewPlan[View Plan v1]
    ViewPlan --> UserFeedback{User Provides Feedback?}
    
    UserFeedback -->|No| Approve[Approve Plan]
    UserFeedback -->|Yes| Revise[POST /draft-pr/jobs/job_id/revise-plan<br/>feedback, concerns, changes]
    
    Revise --> CheckStage{Job Stage?}
    CheckStage -->|Not WAITING_FOR_APPROVAL| ErrorStage[400: Wrong Stage]
    CheckStage -->|WAITING_FOR_APPROVAL| CheckApproved{Already Approved?}
    
    CheckApproved -->|Yes| ErrorApproved[400: Plan Already Approved]
    CheckApproved -->|No| GetLatestPlan[Get Latest Plan Version]
    GetLatestPlan --> CheckWorkspace{Workspace Exists?}
    
    CheckWorkspace -->|No| RecreateWorkspace[Recreate Workspace<br/>From Input Spec]
    RecreateWorkspace --> RecreateSuccess{Success?}
    RecreateSuccess -->|No| ErrorWorkspace[500: Cannot Recreate]
    RecreateSuccess -->|Yes| GenerateRevPlan
    
    CheckWorkspace -->|Yes| GenerateRevPlan[PlanGenerator.revise_plan<br/>Previous Version + Feedback]
    GenerateRevPlan --> CreatePlanV2[Create plan_v2<br/>Increment Version]
    CreatePlanV2 --> StorePlanV2[Store plan_v2 Artifact]
    StorePlanV2 --> InvalidateOldApproval[Invalidate Previous Approval<br/>if exists]
    InvalidateOldApproval --> ComparePlans[PlanComparator.compare_plans<br/>v1 vs v2]
    ComparePlans --> ReturnRevision[Return Revision Response<br/>plan_version, plan_hash, changes_summary]
    
    ReturnRevision --> UserReview2[User Reviews plan_v2]
    UserReview2 --> UserDecision2{Decision?}
    
    UserDecision2 -->|Revise Again| Revise
    UserDecision2 -->|Compare| CompareAPI[GET /draft-pr/jobs/job_id/plans/compare<br/>?from_version=1&to_version=2]
    CompareAPI --> ShowDiff[Show Plan Differences]
    ShowDiff --> UserDecision2
    
    UserDecision2 -->|Approve| Approve
    
    Approve --> End([End])
    ErrorStage --> End
    ErrorApproved --> End
    ErrorWorkspace --> End
    
    style Start fill:#e1f5ff
    style Revise fill:#fff3cd
    style GenerateRevPlan fill:#cfe2ff
    style CreatePlanV2 fill:#d1e7dd
    style Approve fill:#d4edda
    style ErrorStage fill:#f8d7da
    style ErrorApproved fill:#f8d7da
    style ErrorWorkspace fill:#f8d7da
```

## Approval Flow with Safety Checks

```mermaid
flowchart TD
    Start([User: Approve Plan]) --> ApproveAPI[POST /draft-pr/jobs/job_id/approve<br/>plan_hash]
    ApproveAPI --> CheckJobExists{Job Exists?}
    CheckJobExists -->|No| Error404[404: Job Not Found]
    
    CheckJobExists -->|Yes| CheckCancelled{Job Cancelled?}
    CheckCancelled -->|Yes| ErrorCancelled[400: Job Cancelled]
    
    CheckCancelled -->|No| CheckStage{Stage = WAITING_FOR_APPROVAL?}
    CheckStage -->|No| ErrorStage[400: Wrong Stage]
    
    CheckStage -->|Yes| CheckAlreadyApproved{Already Approved<br/>Same Hash?}
    CheckAlreadyApproved -->|Yes| ErrorDuplicate[400: Already Approved]
    
    CheckAlreadyApproved -->|No| AcquireLock[Acquire Redis Lock<br/>draft_pr:approval_lock:job_id<br/>60s timeout]
    AcquireLock --> LockAcquired{Lock Acquired?}
    LockAcquired -->|No| ErrorLock[409: Concurrent Approval]
    
    LockAcquired -->|Yes| GetLatestPlan[Get Latest Plan Version<br/>From Artifact Store]
    GetLatestPlan --> VerifyHash{plan_hash ==<br/>Latest Plan Hash?}
    VerifyHash -->|No| ErrorHashMismatch[400: Hash Mismatch<br/>Must Approve Latest]
    
    VerifyHash -->|Yes| DoubleCheckStage{Stage Still<br/>WAITING_FOR_APPROVAL?}
    DoubleCheckStage -->|No| ErrorStateChanged[409: State Changed]
    
    DoubleCheckStage -->|Yes| DoubleCheckPlan{Plan Still<br/>Matches Hash?}
    DoubleCheckPlan -->|No| ErrorPlanChanged[409: Plan Modified]
    
    DoubleCheckPlan -->|Yes| CreateApproval[Create Approval Record<br/>job_id, plan_hash, approver]
    CreateApproval --> UpdateJob[Update Job Status<br/>approved_plan_hash<br/>stage=APPLYING]
    UpdateJob --> PersistStatus[Persist Job Status to Redis<br/>For Crash Recovery]
    PersistStatus --> StoreApproval[Store Approval Artifact]
    StoreApproval --> StoreSuccess{Stored Successfully?}
    
    StoreSuccess -->|No| RollbackJob[Rollback Job State<br/>Remove approved_plan_hash]
    RollbackJob --> ErrorStore[500: Failed to Store]
    
    StoreSuccess -->|Yes| ReleaseLock[Release Redis Lock]
    ReleaseLock --> CheckCancelAgain{Job Cancelled<br/>During Approval?}
    CheckCancelAgain -->|Yes| RollbackApproval[Rollback Approval State]
    RollbackApproval --> ErrorCancelDuring[409: Cancelled During Approval]
    
    CheckCancelAgain -->|No| ContinuePipeline[Continue Pipeline<br/>continue_pipeline_after_approval]
    ContinuePipeline --> MonitorCancel[Monitor Cancellation<br/>During Execution]
    MonitorCancel --> ExecuteApply[Execute APPLY Stage]
    ExecuteApply --> Success([Success: Pipeline Continues])
    
    Error404 --> End
    ErrorCancelled --> End
    ErrorStage --> End
    ErrorDuplicate --> End
    ErrorLock --> End
    ErrorHashMismatch --> End
    ErrorStateChanged --> End
    ErrorPlanChanged --> End
    ErrorStore --> End
    ErrorCancelDuring --> End
    
    style Start fill:#e1f5ff
    style AcquireLock fill:#fff3cd
    style VerifyHash fill:#fff3cd
    style CreateApproval fill:#d1e7dd
    style ContinuePipeline fill:#cfe2ff
    style Success fill:#d4edda
    style Error404 fill:#f8d7da
    style ErrorCancelled fill:#f8d7da
    style ErrorStage fill:#f8d7da
    style ErrorDuplicate fill:#f8d7da
    style ErrorLock fill:#f8d7da
    style ErrorHashMismatch fill:#f8d7da
    style ErrorStateChanged fill:#f8d7da
    style ErrorPlanChanged fill:#f8d7da
    style ErrorStore fill:#f8d7da
    style ErrorCancelDuring fill:#f8d7da
```

## Artifact Persistence Flow

```mermaid
flowchart LR
    Pipeline[Pipeline Execution] --> Artifact1[Input Spec<br/>story_key, repos, scope]
    Pipeline --> Artifact2[Workspace Fingerprint<br/>repos, paths, hash]
    Pipeline --> Artifact3[Plan Versions<br/>plan_v1, plan_v2, ...]
    Pipeline --> Artifact4[Approval Record<br/>job_id, plan_hash, approver]
    Pipeline --> Artifact5[Git Diff<br/>code changes]
    Pipeline --> Artifact6[Validation Logs<br/>test/lint/build output]
    Pipeline --> Artifact7[PR Metadata<br/>branch, PR URL, title]
    
    Artifact1 --> Store[ArtifactStore.store_artifact<br/>job_id, artifact_type, data]
    Artifact2 --> Store
    Artifact3 --> Store
    Artifact4 --> Store
    Artifact5 --> Store
    Artifact6 --> Store
    Artifact7 --> Store
    
    Store --> Retry{Storage Success?}
    Retry -->|No| RetryLogic[Retry with Exponential Backoff<br/>Up to 3 attempts]
    RetryLogic --> Retry
    
    Retry -->|Yes| Validate[Post-Storage Validation<br/>Verify Artifact Written]
    Validate --> Persist[Persist to Disk<br/>data/artifacts/job_id/]
    
    Persist --> API[API Endpoints<br/>GET /draft-pr/jobs/job_id/artifacts]
    API --> Retrieve[ArtifactStore.retrieve_artifact<br/>job_id, artifact_type]
    Retrieve --> Return[Return Artifact to User]
    
    style Pipeline fill:#e1f5ff
    style Store fill:#fff3cd
    style Persist fill:#d1e7dd
    style API fill:#cfe2ff
    style Return fill:#d4edda
```

## Component Interactions

```mermaid
graph TB
    API[API Routes<br/>draft_pr.py] --> Worker[ARQ Worker<br/>process_draft_pr_worker]
    API --> Pipeline[DraftPRPipeline]
    
    Worker --> Pipeline
    Worker --> JIRA[JiraClient<br/>Fetch Story]
    
    Pipeline --> PlanGen[PlanGenerator<br/>Generate/Revise Plans]
    Pipeline --> WorkspaceMgr[WorkspaceManager<br/>Clone Repos, Manage Workspaces]
    Pipeline --> CodeApplier[CodeApplier<br/>Apply Changes with Git Safety]
    Pipeline --> Verifier[Verifier<br/>Run Tests/Lint/Build]
    Pipeline --> PackageSvc[PackageService<br/>Generate PR Metadata]
    Pipeline --> PRCreator[DraftPRCreator<br/>Create Branch & PR]
    Pipeline --> ArtifactStore[ArtifactStore<br/>Persist All Artifacts]
    
    PlanGen --> OpenCode[OpenCodeRunner<br/>Docker Container Execution]
    PlanGen --> LLM[LLMClient<br/>Direct LLM Calls]
    
    CodeApplier --> OpenCode
    CodeApplier --> Git[Git Operations<br/>Checkpoint, Commit, Push]
    
    PRCreator --> Bitbucket[BitbucketClient<br/>Create Branch, PR]
    
    ArtifactStore --> Disk[File System<br/>data/artifacts/job_id/]
    
    Pipeline --> Redis[Redis<br/>Job Status Persistence<br/>Cancellation Flags<br/>Approval Locks]
    
    style API fill:#e1f5ff
    style Worker fill:#fff3cd
    style Pipeline fill:#cfe2ff
    style PlanGen fill:#d1e7dd
    style CodeApplier fill:#d1e7dd
    style Verifier fill:#d1e7dd
    style PRCreator fill:#d1e7dd
    style ArtifactStore fill:#d1e7dd
```

## Key Features Highlighted

1. **Pipeline Stages**: 7 distinct stages from CREATED to COMPLETED
2. **Two Modes**: Normal (human approval) and YOLO (auto-approval)
3. **Plan Iteration**: Users can revise plans multiple times
4. **Safety Mechanisms**: Plan hash binding, plan-apply guards, git transaction safety
5. **Cancellation Support**: Can cancel at any stage with proper cleanup
6. **Artifact Persistence**: All artifacts stored for auditability
7. **Error Handling**: Comprehensive error handling with rollback capabilities
8. **Distributed Locking**: Prevents concurrent approval requests
9. **Crash Recovery**: Job status persisted to Redis for recovery
