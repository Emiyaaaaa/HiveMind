package io.agentflow.api.controller;

import io.agentflow.api.config.AgentflowProperties;
import io.agentflow.api.dto.HealthResponse;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/v1")
public class HealthController {

    private final AgentflowProperties props;

    public HealthController(AgentflowProperties props) {
        this.props = props;
    }

    @GetMapping("/health")
    public HealthResponse health() {
        return new HealthResponse("ok", props.getVersion(), props.getAdapters());
    }
}
