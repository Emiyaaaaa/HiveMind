package io.agentflow.api.controller;

import io.agentflow.api.dto.BatchCreateRequest;
import io.agentflow.api.dto.BatchResponse;
import io.agentflow.api.dto.RunResponse;
import io.agentflow.api.service.BatchService;
import jakarta.validation.Valid;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/v1/batches")
public class BatchesController {

    private final BatchService service;

    public BatchesController(BatchService service) {
        this.service = service;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.ACCEPTED)
    public BatchResponse create(@Valid @RequestBody BatchCreateRequest payload) {
        return service.create(payload);
    }

    @GetMapping
    public List<BatchResponse> list(@RequestParam(defaultValue = "50") int limit) {
        return service.list(limit);
    }

    @GetMapping("/{id}")
    public BatchResponse get(@PathVariable String id) {
        return service.get(id);
    }

    @GetMapping("/{id}/runs")
    public List<RunResponse> listRuns(@PathVariable String id) {
        return service.listRuns(id);
    }
}
