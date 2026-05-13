package io.agentflow.api.controller;

import io.agentflow.api.config.AgentflowProperties;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class RootController {

    private final AgentflowProperties props;

    public RootController(AgentflowProperties props) {
        this.props = props;
    }

    @GetMapping("/")
    public Map<String, String> root() {
        return Map.of("name", "agentflow", "version", props.getVersion(), "docs", "/v3/api-docs");
    }
}
