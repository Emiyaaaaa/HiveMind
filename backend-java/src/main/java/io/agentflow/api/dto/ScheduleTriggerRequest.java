package io.agentflow.api.dto;

public class ScheduleTriggerRequest {
    private boolean advance;

    public boolean isAdvance() {
        return advance;
    }

    public void setAdvance(boolean advance) {
        this.advance = advance;
    }
}
