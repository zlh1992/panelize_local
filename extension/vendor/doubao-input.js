// Extracted from Panelize fb9cc70, MIT. See Panelize.LICENSE.
const doubaoInputs = [
      '#input-engine-container .ProseMirror[contenteditable="true"]',
      '#input-engine-container .semi-input-textarea-wrapper textarea',
      '.semi-input-textarea-wrapper textarea',
      '#input-engine-container textarea',
      'textarea.semi-input-textarea',
      'textarea.semi-input-textarea[placeholder="发消息..."]',
      'textarea[placeholder="发消息..."]',
      '[data-slate-editor="true"][contenteditable="true"]',
      '.flow-chat-editor [data-slate-editor="true"][contenteditable="true"]',
      '.flow-chat-editor [contenteditable="true"][role="textbox"]',
      '.flow-chat-editor [contenteditable="true"]',
      '[contenteditable="true"][role="textbox"]'
    ];
  function setFormControlValue(element, value) {
    const prototype = element.tagName === 'INPUT'
      ? window.HTMLInputElement.prototype
      : window.HTMLTextAreaElement.prototype;
    const nativeSetter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;

    if (nativeSetter) {
      nativeSetter.call(element, value);
    } else {
      element.value = value;
    }

    element.dispatchEvent(new Event('input', { bubbles: true }));
    element.dispatchEvent(new Event('change', { bubbles: true }));

    if (typeof element.value === 'string') {
      element.selectionStart = element.selectionEnd = element.value.length;
    }
  }
  function injectTextIntoElement(element, text, provider = null) {
    if (!element || !text || typeof text !== 'string' || text.trim() === '') {
      return false;
    }

    try {
      const isTextarea = element.tagName === 'TEXTAREA' || element.tagName === 'INPUT';
      const isContentEditable = element.isContentEditable || element.getAttribute('contenteditable') === 'true';

      if (!isTextarea && !isContentEditable) {
        console.warn('Element is not a textarea or contenteditable:', element);
        return false;
      }

      if (isTextarea) {
        // For textarea/input elements
        const currentValue = element.value || '';
        const newValue = currentValue + text;

        setFormControlValue(element, newValue);
      } else {
        // For contenteditable elements - append text without clearing existing content
        element.focus();

        // Move cursor to end first
        try {
          const selection = window.getSelection();
          const range = document.createRange();
          range.selectNodeContents(element);
          range.collapse(false); // Collapse to end
          selection.removeAllRanges();
          selection.addRange(range);
        } catch (e) {
          // Ignore selection errors in cross-origin context
        }

        if (provider === 'qwen-cn') {
          // Qwen China uses Slate's beforeinput handler as its source of truth.
          // A DOM-only insertion is visible but leaves the send control disabled.
          const beforeInputEvent = new InputEvent('beforeinput', {
            inputType: 'insertText',
            data: text,
            bubbles: true,
            cancelable: true,
            composed: true
          });

          if (!element.dispatchEvent(beforeInputEvent)) {
            return true;
          }
        }

        // Use execCommand insertText to append - works well with ProseMirror/Lexical/Quill
        let inserted = false;
        try {
          inserted = document.execCommand('insertText', false, text);
        } catch (e) {
          // execCommand not available in some contexts
        }

        if (!inserted) {
          // Fallback: manually append text node
          const textNode = document.createTextNode(text);
          element.appendChild(textNode);
          element.dispatchEvent(new Event('input', { bubbles: true }));
        }

        // Ensure cursor is at the end after insertion
        try {
          const selection = window.getSelection();
          const range = document.createRange();
          range.selectNodeContents(element);
          range.collapse(false);
          selection.removeAllRanges();
          selection.addRange(range);
        } catch (e) {
          // Ignore selection errors in cross-origin context
        }
      }

      return true;
    } catch (error) {
      console.error('Error injecting text:', error);
      return false;
    }
  }
