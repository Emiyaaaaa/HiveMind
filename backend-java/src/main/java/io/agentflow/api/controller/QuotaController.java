package io.agentflow.api.controller;

import io.agentflow.api.dto.AgentQuotaStatusResponse;
import io.agentflow.api.dto.QuotaConfigRequest;
import io.agentflow.api.service.AgentQuotaService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/v1")
public class QuotaController {

    private final AgentQuotaService quotas;

    public QuotaController(AgentQuotaService quotas) {
        this.quotas = quotas;
    }

    @GetMapping("/projects/{projectId}/quota")
    public AgentQuotaStatusResponse projectQuota(@PathVariable String projectId) {
        return quotas.projectStatus(projectId);
    }

    @PutMapping("/projects/{projectId}/quota")
    public AgentQuotaStatusResponse putProjectQuota(
            @PathVariable String projectId, @RequestBody(required = false) QuotaConfigRequest body) {
        return quotas.upsertProject(projectId, body);
    }

    @GetMapping("/tenant/quota")
    public AgentQuotaStatusResponse tenantQuota() {
        return quotas.tenantStatus();
    }

    @PutMapping("/tenant/quota")
    public AgentQuotaStatusResponse putTenantQuota(
            @RequestBody(required = false) QuotaConfigRequest body) {
        return quotas.upsertTenant(body);
    }
}
