package io.agentflow.api.controller;

import io.agentflow.api.dto.AgentCreateRequest;
import io.agentflow.api.dto.AgentResponse;
import io.agentflow.api.dto.AgentUpdateRequest;
import io.agentflow.api.dto.AgentVersionDiffResponse;
import io.agentflow.api.dto.AgentVersionResponse;
import io.agentflow.api.service.AgentService;
import jakarta.validation.Valid;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/v1/agents")
public class AgentsController {

    private final AgentService service;

    public AgentsController(AgentService service) {
        this.service = service;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public AgentResponse create(@Valid @RequestBody AgentCreateRequest payload) {
        return service.create(payload);
    }

    @GetMapping
    public List<AgentResponse> list() {
        return service.list();
    }

    @GetMapping("/{id}")
    public AgentResponse get(@PathVariable String id) {
        return service.get(id);
    }

    @PatchMapping("/{id}")
    public AgentResponse update(
            @PathVariable String id, @RequestBody AgentUpdateRequest payload) {
        return service.update(id, payload);
    }

    @GetMapping("/{id}/versions")
    public List<AgentVersionResponse> listVersions(@PathVariable String id) {
        return service.listVersions(id);
    }

    @GetMapping("/{id}/versions/diff")
    public AgentVersionDiffResponse diff(
            @PathVariable String id,
            @RequestParam("from") int from,
            @RequestParam("to") int to) {
        return service.diff(id, from, to);
    }

    @GetMapping("/{id}/versions/{version}")
    public AgentVersionResponse getVersion(
            @PathVariable String id, @PathVariable int version) {
        return service.getVersion(id, version);
    }

    @PostMapping("/{id}/versions/{version}/restore")
    public AgentResponse restore(@PathVariable String id, @PathVariable int version) {
        return service.restore(id, version);
    }
}
