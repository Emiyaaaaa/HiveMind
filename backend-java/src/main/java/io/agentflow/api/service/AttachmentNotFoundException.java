package io.agentflow.api.service;

public class AttachmentNotFoundException extends RuntimeException {

    public AttachmentNotFoundException(String attachmentId) {
        super(attachmentId);
    }
}
