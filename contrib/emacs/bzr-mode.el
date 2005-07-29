;;; bzr.el -- version control commands for Bazaar-NG.
;;; Copyright 2005  Luke Gorrie <luke@member.fsf.org>
;;;
;;; bzr.el is free software distributed under the terms of the GNU
;;; General Public Licence, version 2. For details see the file
;;; COPYING in the GNU Emacs distribution.
;;;
;;; This is MAJOR copy & paste job from darcs.el

(eval-when-compile
  (unless (fboundp 'define-minor-mode)
    (require 'easy-mmode)
    (defalias 'define-minor-mode 'easy-mmode-define-minor-mode))
  (when (featurep 'xemacs)
    (require 'cl)))

;;;; Configurables

(defvar bzr-command-prefix "\C-cb"
  ;; This default value breaks the Emacs rules and uses a sequence
  ;; reserved for the user's own custom bindings. That's not good but
  ;; I can't think of a decent standard one. -luke (14/Mar/2005)
  "Prefix sequence for bzr-mode commands.")

(defvar bzr-command "bzr"
  "*Shell command to execute bzr.")

(defvar bzr-buffer "*bzr-command*"
  "Buffer for user-visible bzr command output.")

;;;; Minor-mode

(define-minor-mode bzr-mode
  "\\{bzr-mode-map}"
  nil
  " bzr"
  ;; Coax define-minor-mode into creating a keymap.
  ;; We'll fill it in manually though because define-minor-mode seems
  ;; hopeless for changing bindings without restarting Emacs.
  `((,bzr-command-prefix . fake)))

(defvar bzr-mode-commands-map nil
  "Keymap for bzr-mode commands.
This map is bound to a prefix sequence in `bzr-mode-map'.")

(defconst bzr-command-keys '(("l" bzr-log)
                             ("d" bzr-diff)
                             ("s" bzr-status)
                             ("c" bzr-commit))
  "Keys to bind in `bzr-mode-commands-map'.")

(defun bzr-init-command-keymap ()
  "Bind the bzr-mode keys.
This command can be called interactively to redefine the keys from
`bzr-commands-keys'."
  (interactive)
  (setq bzr-mode-commands-map (make-sparse-keymap))
  (dolist (spec bzr-command-keys)
    (define-key bzr-mode-commands-map (car spec) (cadr spec)))
  (define-key bzr-mode-map bzr-command-prefix bzr-mode-commands-map))

(bzr-init-command-keymap)


;;;; Commands

(defun bzr-log ()
  "Run \"bzr log\" in the repository top-level."
  (interactive)
  (bzr "log"))

(defun bzr-diff ()
  "Run \"bzr diff\" in the repository top-level."
  (interactive)
  (save-some-buffers)
  (bzr-run-command (bzr-command "diff") 'diff-mode))

(defun bzr-status ()
  "Run \"bzr diff\" in the repository top-level."
  (interactive)
  (bzr "status"))

(defun bzr-commit (message)
  "Run \"bzr diff\" in the repository top-level."
  (interactive "sCommit message: ")
  (save-some-buffers)
  (bzr "commit -m %s" (shell-quote-argument message)))

;;;; Utilities

(defun bzr (format &rest args)
  (bzr-run-command (apply #'bzr-command format args)))

(defun bzr-command (format &rest args)
  (concat bzr-command " " (apply #'format format args)))

(defun bzr-run-command (command &optional pre-view-hook)
  "Run COMMAND at the top-level and view the result in another window.
PRE-VIEW-HOOK is an optional function to call before entering
view-mode. This is useful to set the major-mode of the result buffer,
because if you did it afterwards then it would zap view-mode."
  (bzr-cleanup)
  (let ((toplevel (bzr-toplevel)))
    (with-current-buffer (get-buffer-create bzr-buffer)
      ;; prevent `shell-command' from printing output in a message
      (let ((max-mini-window-height 0))
        (let ((default-directory toplevel))
          (shell-command command t)))
      (goto-char (point-min))
      (when pre-view-hook
        (funcall pre-view-hook))))
  (if (zerop (buffer-size (get-buffer bzr-buffer)))
      (message "(bzr command finished with no output.)")
    (view-buffer-other-window bzr-buffer)
    ;; Bury the buffer when dismissed.
    (with-current-buffer (get-buffer bzr-buffer)
      (setq view-exit-action #'bury-buffer))))

(defun bzr-current-file ()
  (or (buffer-file-name)
      (error "Don't know what file to use!")))

(defun bzr-cleanup (&optional buffer-name)
  "Cleanup before executing a command.
BUFFER-NAME is the command's output buffer."
  (let ((name (or buffer-name bzr-buffer)))
    (when (get-buffer bzr-buffer)
      (kill-buffer bzr-buffer))))

(defun bzr-toplevel ()
  "Return the top-level directory of the repository."
  (let ((dir (bzr-find-repository)))
    (if dir
        (file-name-directory dir)
      (error "Can't find bzr repository top-level."))))
  
(defun bzr-find-repository (&optional start-directory)
  "Return the enclosing \".bzr\" directory, or nil if there isn't one."
  (when (and (buffer-file-name)
             (file-directory-p (file-name-directory (buffer-file-name))))
    (let ((dir (or start-directory
                   default-directory
                   (error "No start directory given."))))
      (or (car (directory-files dir t "^\\.bzr$"))
          (let ((next-dir (file-name-directory (directory-file-name dir))))
            (unless (equal dir next-dir)
              (bzr-find-repository next-dir)))))))

;;;; Hook setup
;;;
;;; Automaticaly enter bzr-mode when we open a file that's under bzr
;;; control, i.e. if the .bzr directory can be found.

(defun bzr-find-file-hook ()
  "Enable bzr-mode if the file is inside a bzr repository."
  ;; Note: This function is called for every file that Emacs opens so
  ;; it mustn't make any mistakes.
  (when (bzr-find-repository) (bzr-mode 1)))

(add-hook 'find-file-hooks 'bzr-find-file-hook)

(provide 'bzr)

