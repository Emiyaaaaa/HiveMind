package io.agentflow.api.controller;

import io.agentflow.api.dto.EraseRunDataResponse;
import io.agentflow.api.dto.EraseTenantDataResponse;
import io.agentflow.api.dto.RetentionPurgeRequest;
import io.agentflow.api.dto.RetentionPurgeResponse;
import io.agentflow.api.service.RetentionService;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/v1")
public class RetentionController {

    private final RetentionService service;

    public RetentionController(RetentionService service) {
        this.service = service;
    }

    @PostMapping("/runs/{runId}/erase")
    public EraseRunDataResponse eraseRun(@PathVariable String runId) {
        return service.eraseRunData(runId);
    }

    @PostMapping("/organization/erase")
    public EraseTenantDataResponse eraseOrganization() {
        return service.eraseTenantData();
    }

    @PostMapping("/retention/purge")
    public RetentionPurgeResponse purge(@RequestBody(required = false) RetentionPurgeRequest payload) {
        RetentionPurgeRequest req = payload == null ? new RetentionPurgeRequest() : payload;
        return service.purgeExpired(req.getTenantId(), req.isDryRun());
    }
}
