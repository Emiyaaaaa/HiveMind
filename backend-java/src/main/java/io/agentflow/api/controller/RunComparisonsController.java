package io.agentflow.api.controller;

import io.agentflow.api.dto.RunComparisonPreviewRequest;
import io.agentflow.api.dto.RunComparisonResponse;
import io.agentflow.api.service.RunComparisonService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/v1/run-comparisons")
public class RunComparisonsController {

    private final RunComparisonService service;

    public RunComparisonsController(RunComparisonService service) {
        this.service = service;
    }

    @PostMapping("/preview")
    public RunComparisonResponse preview(
            @Valid @RequestBody RunComparisonPreviewRequest payload) {
        return service.preview(payload);
    }
}
