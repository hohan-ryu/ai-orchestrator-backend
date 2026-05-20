---
title: AI Orchestrator — core/ 컴포넌트 다이어그램
---
flowchart TD

    %% ══════════════════════════════════════════
    %% LangGraph 실행 흐름
    %% ══════════════════════════════════════════
    subgraph flow["⚡ LangGraph 실행 흐름"]
        direction LR
        S(["START"])
        N1["analyze_intent"]
        N2["plan_tasks"]
        N3["execute_tasks"]
        NE["handle_error"]
        E(["END"])

        S  --> N1
        N1 -->|continue| N2
        N1 -->|error|    NE
        N2 -->|continue| N3
        N2 -->|error|    NE
        N3 --> E
        NE --> E
    end

    %% ══════════════════════════════════════════
    %% core/ 내부 컴포넌트
    %% ══════════════════════════════════════════
    subgraph core["📦 core/"]

        subgraph graph_py["graph.py"]
            BG["build_graph(checkpointer?)\n→ CompiledGraph"]
            SG["set_graph / get_graph\n싱글톤 관리"]
            WN["_wrap_node(fn, name)\n예외 → error 상태 변환"]
            SC["_should_continue(state)\n→ 'continue' | 'error'"]
            HE["handle_error(state)"]
        end

        subgraph nodes_pkg["nodes/"]
            subgraph ia["intent_analyzer.py"]
                AI["analyze_intent(state)\n① run_pipeline() 호출\n② confidence 낮음 → interrupt HITL\n③ StreamEvent 반환"]
            end
            subgraph tp["task_planner.py"]
                PT["plan_tasks(state)\n① AgentRegistry 에이전트 목록 조회\n② LLMGateway.complete() → JSON 파싱\n③ TaskPlan · StreamEvent 반환"]
            end
            subgraph te["task_executor.py"]
                ET["execute_tasks(state)\n① HITL: 플랜 실행 전 확인\n② Task 순차 실행\n   ├ agent_id ✓ → AgentExecutor\n   └ agent_id ✗ → LLMGateway\n③ 최종 답변 생성 · StreamEvent 반환"]
            end
        end

        subgraph state_py["state.py"]
            OS["OrchestratorState (TypedDict)\n─────────────────────────────\nuser_input : str\nsession_id : str\nintent : Intent | None\nintent_tier : 'rule'|'cache'|'llm' | None\nplan : TaskPlan | None\ncompleted_tasks : list[Task]  ← 누적\nstream_events : list[StreamEvent]  ← 누적\nfinal_answer : str\nerror : str | None"]
        end

        subgraph utils_py["utils.py"]
            EJ["extract_json(text)\nJSON 블록 추출"]
            SPJ["safe_parse_json(text)\nLLM 응답 JSON 파싱"]
            IL["invoke_llm(llm, sys, user)\nLangChain 호출 헬퍼"]
        end

        subgraph factory_py["llm_factory.py  ⚠ 레거시"]
            GL["get_llm(model, settings)\n→ BaseChatModel\ngoogle / anthropic (직접 생성)"]
        end
    end

    %% ══════════════════════════════════════════
    %% 외부 의존성
    %% ══════════════════════════════════════════
    subgraph ext["🔗 외부 의존성"]
        direction LR

        subgraph lg["LangGraph"]
            LG_SG["StateGraph / END"]
            LG_CP["MemorySaver\n(또는 AsyncRedisSaver)"]
            LG_IT["interrupt()"]
        end

        subgraph cmn["common/"]
            CMN_ST["get_settings() · Settings"]
            CMN_SC["schemas/models\nIntent · Task · TaskPlan\nStreamEvent · HITLPayload"]
        end

        subgraph itn["intent/"]
            ITN_PL["run_pipeline()\nrule → cache → llm 순차 처리"]
        end

        subgraph llms["llms/"]
            LLM_GW["get_gateway() · LLMGateway\n동적 프로바이더 체인"]
        end

        subgraph agts["agents/"]
            AGT_RG["AgentRegistry\nget_registry()"]
            AGT_EX["AgentExecutor"]
        end
    end

    %% ══════════════════════════════════════════
    %% 관계 — graph.py
    %% ══════════════════════════════════════════
    BG -->|"StateGraph(OrchestratorState)"| LG_SG
    BG -->|"compile(checkpointer)"| LG_CP
    BG -->|"모든 노드 래핑"| WN
    BG -->|"conditional_edges"| SC
    BG -.->|"add_node · 그래프 등록"| flow
    SG -.->|"lazy init"| BG

    %% ══════════════════════════════════════════
    %% 관계 — nodes/
    %% ══════════════════════════════════════════
    AI -->|"run_pipeline(user_input)"| ITN_PL
    AI -->|"interrupt() HITL"| LG_IT
    AI -->|"hitl_clarify_threshold"| CMN_ST

    PT -->|"complete(planner_model)"| LLM_GW
    PT -->|"list_enabled()"| AGT_RG
    PT -->|"safe_parse_json()"| SPJ
    PT -->|"max_tasks · planner_model"| CMN_ST

    ET -->|"complete(executor_model)"| LLM_GW
    ET -->|"get(agent_id)"| AGT_RG
    ET -->|"execute(agent_id, tool, input)"| AGT_EX
    ET -->|"interrupt() HITL"| LG_IT
    ET -->|"hitl_confirm_plan · executor_model"| CMN_ST

    %% ══════════════════════════════════════════
    %% 관계 — 공통
    %% ══════════════════════════════════════════
    OS  -->|"타입 import"| CMN_SC
    SPJ -->|"내부 호출"| EJ
    GL  -->|"llm_provider · api_key"| CMN_ST

    %% ══════════════════════════════════════════
    %% 스타일
    %% ══════════════════════════════════════════
    classDef startEnd  fill:#064e3b,stroke:#4ade80,color:#4ade80,font-weight:bold
    classDef flowNode  fill:#1e293b,stroke:#6366f1,color:#a5b4fc
    classDef graphComp fill:#1e293b,stroke:#10b981,color:#6ee7b7
    classDef nodeComp  fill:#1e293b,stroke:#0ea5e9,color:#7dd3fc
    classDef stateComp fill:#1e293b,stroke:#8b5cf6,color:#c4b5fd
    classDef utilComp  fill:#273548,stroke:#475569,color:#94a3b8
    classDef legacyComp fill:#1c1917,stroke:#78716c,color:#78716c
    classDef extComp   fill:#0f172a,stroke:#334155,color:#64748b

    class S,E startEnd
    class N1,N2,N3,NE flowNode
    class BG,SG,WN,SC,HE graphComp
    class AI,PT,ET nodeComp
    class OS stateComp
    class EJ,SPJ,IL utilComp
    class GL legacyComp
    class LG_SG,LG_CP,LG_IT,CMN_ST,CMN_SC,ITN_PL,LLM_GW,AGT_RG,AGT_EX extComp
