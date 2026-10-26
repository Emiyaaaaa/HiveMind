package io.agentflow.api.jobs;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.agentflow.api.config.AgentflowProperties;
import io.temporal.api.enums.v1.WorkflowIdReusePolicy;
import io.temporal.client.WorkflowClient;
import io.temporal.client.WorkflowClientOptions;
import io.temporal.client.WorkflowExecutionAlreadyStarted;
import io.temporal.client.WorkflowOptions;
import io.temporal.client.WorkflowStub;
import io.temporal.serviceclient.WorkflowServiceStubs;
import io.temporal.serviceclient.WorkflowServiceStubsOptions;
import java.time.Instant;
import java.util.Map;
import org.springframework.stereotype.Component;

@Component
public class TemporalWorkflowClient {

    static final String WORKFLOW_NAME = "RunWorkflow";
    static final String SIGNAL_RESUME = "resume";
    static final String SIGNAL_CANCEL = "cancel";

    private final ObjectMapper mapper;
    private final AgentflowProperties props;
    private volatile WorkflowClient client;
    private volatile WorkflowServiceStubs service;

    public TemporalWorkflowClient(ObjectMapper mapper, AgentflowProperties props) {
        this.mapper = mapper;
        this.props = props;
    }

    public void startOrResume(String runId, String agentId, String adapter, Map<String, String> traceContext) {
        RunJob job = new RunJob(runId, agentId, adapter, Instant.now(), traceContext);
        Map<String, Object> payload = mapper.convertValue(job, new TypeReference<>() {});
        payload.put("_heartbeat_seconds", props.getTemporal().getActivityHeartbeatSeconds());
        payload.put("_start_to_close_seconds", props.getTemporal().getActivityStartToCloseSeconds());
        payload.put("_max_attempts", props.getTemporal().getActivityMaxAttempts());
        String workflowId = workflowId(runId);
        WorkflowStub stub = client().newUntypedWorkflowStub(
                WORKFLOW_NAME,
                WorkflowOptions.newBuilder()
                        .setTaskQueue(props.getTemporal().getTaskQueue())
                        .setWorkflowId(workflowId)
                        .setWorkflowIdReusePolicy(WorkflowIdReusePolicy.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE_FAILED_ONLY)
                        .build());
        try {
            stub.start(payload);
        } catch (WorkflowExecutionAlreadyStarted ignored) {
            client().newUntypedWorkflowStub(workflowId).signal(SIGNAL_RESUME, payload);
        }
    }

    public void signalCancel(String runId) {
        try {
            client().newUntypedWorkflowStub(workflowId(runId)).signal(SIGNAL_CANCEL);
        } catch (Exception ignored) {
            // Missing or completed workflow: the Python worker / DB row remains source of truth.
        }
    }

    private WorkflowClient client() {
        WorkflowClient existing = client;
        if (existing != null) {
            return existing;
        }
        synchronized (this) {
            if (client == null) {
                service = WorkflowServiceStubs.newServiceStubs(
                        WorkflowServiceStubsOptions.newBuilder()
                                .setTarget(props.getTemporal().getTarget())
                                .build());
                client = WorkflowClient.newInstance(
                        service,
                        WorkflowClientOptions.newBuilder()
                                .setNamespace(props.getTemporal().getNamespace())
                                .build());
            }
            return client;
        }
    }

    static String workflowId(String runId) {
        return "run:" + runId;
    }
}
