package io.agentflow.api.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Size;
import java.util.List;

public record RegressionExecutionCreateRequest(
        @NotEmpty @Size(max = 100) List<@NotBlank String> baselineRunIds) {}
