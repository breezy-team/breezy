;;; brz.el -- version control commands for Breezy.
;;; Copyright 2005  Luke Gorrie <luke@member.fsf.org>
;;;
;;; brz.el is free software distributed under the terms of the GNU
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

(defvar brz-command-prefix "\C-cb"
  ;; This default value breaks the Emacs rules and uses a sequence
  ;; reserved for the user's own custom bindings. That's not good but
  ;; I can't think of a decent standard one. -luke (14/Mar/2005)
  "Prefix sequence for brz-mode commands.")

(defvar brz-command "brz"
  "*Shell command to execute brz.")

(defvar brz-buffer "*brz-command*"
  "Buffer for user-visible brz command output.")

;;;; Minor-mode

(define-minor-mode brz-mode
  "\\{brz-mode-map}"
  nil
  " brz"
  ;; Coax define-minor-mode into creating a keymap.
  ;; We'll fill it in manually though because define-minor-mode seems
  ;; hopeless for changing bindings without restarting Emacs.
  `((,brz-command-prefix . fake)))

(defvar brz-mode-commands-map nil
  "Keymap for brz-mode commands.
This map is bound to a prefix sequence in `brz-mode-map'.")

(defconst brz-command-keys '(("l" brz-log)
                             ("d" brz-diff)
                             ("s" brz-status)
                             ("c" brz-commit))
  "Keys to bind in `brz-mode-commands-map'.")

(defun brz-init-command-keymap ()
  "Bind the brz-mode keys.
This command can be called interactively to redefine the keys from
`brz-commands-keys'."
  (interactive)
  (setq brz-mode-commands-map (make-sparse-keymap))
  (dolist (spec brz-command-keys)
    (define-key brz-mode-commands-map (car spec) (cadr spec)))
  (define-key brz-mode-map brz-command-prefix brz-mode-commands-map))

(brz-init-command-keymap)


;;;; Commands

(defun brz-log ()
  "Run \"brz log\" in the repository top-level."
  (interactive)
  (brz "log"))

(defun brz-diff ()
  "Run \"brz diff\" in the repository top-level."
  (interactive)
  (save-some-buffers)
  (brz-run-command (brz-command "diff") 'diff-mode))

(defun brz-status ()
  "Run \"brz diff\" in the repository top-level."
  (interactive)
  (brz "status"))

(defun brz-commit (message)
  "Run \"brz diff\" in the repository top-level."
  (interactive "sCommit message: ")
  (save-some-buffers)
  (brz "commit -m %s" (shell-quote-argument message)))

;;;; Utilities

(defun brz (format &rest args)
  (brz-run-command (apply #'brz-command format args)))

(defun brz-command (format &rest args)
  (concat brz-command " " (apply #'format format args)))

(defun brz-run-command (command &optional pre-view-hook)
  "Run COMMAND at the top-level and view the result in another window.
PRE-VIEW-HOOK is an optional function to call before entering
view-mode. This is useful to set the major-mode of the result buffer,
because if you did it afterwards then it would zap view-mode."
  (brz-cleanup)
  (let ((toplevel (brz-toplevel)))
    (with-current-buffer (get-buffer-create brz-buffer)
      ;; prevent `shell-command' from printing output in a message
      (let ((max-mini-window-height 0))
        (let ((default-directory toplevel))
          (shell-command command t)))
      (goto-char (point-min))
      (when pre-view-hook
        (funcall pre-view-hook))))
  (if (zerop (buffer-size (get-buffer brz-buffer)))
      (message "(brz command finished with no output.)")
    (view-buffer-other-window brz-buffer)
    ;; Bury the buffer when dismissed.
    (with-current-buffer (get-buffer brz-buffer)
      (setq view-exit-action #'bury-buffer))))

(defun brz-current-file ()
  (or (buffer-file-name)
      (error "Don't know what file to use!")))

(defun brz-cleanup (&optional buffer-name)
  "Cleanup before executing a command.
BUFFER-NAME is the command's output buffer."
  (let ((name (or buffer-name brz-buffer)))
    (when (get-buffer brz-buffer)
      (kill-buffer brz-buffer))))

(defun brz-toplevel ()
  "Return the top-level directory of the repository."
  (let ((dir (brz-find-repository)))
    (if dir
        (file-name-directory dir)
      (error "Can't find brz repository top-level."))))
  
(defun brz-find-repository (&optional start-directory)
  "Return the enclosing \".bzr\" directory, or nil if there isn't one."
  (when (and (buffer-file-name)
             (file-directory-p (file-name-directory (buffer-file-name))))
    (let ((dir (or start-directory
                   default-directory
                   (error "No start directory given."))))
      (or (car (directory-files dir t "^\\.bzr$"))
          (let ((next-dir (file-name-directory (directory-file-name dir))))
            (unless (equal dir next-dir)
              (brz-find-repository next-dir)))))))

;;;; Hook setup
;;;
;;; Automaticaly enter brz-mode when we open a file that's under brz
;;; control, i.e. if the .bzr directory can be found.

(defun brz-find-file-hook ()
  "Enable brz-mode if the file is inside a brz repository."
  ;; Note: This function is called for every file that Emacs opens so
  ;; it mustn't make any mistakes.
  (when (brz-find-repository) (brz-mode 1)))

(add-hook 'find-file-hooks 'brz-find-file-hook)

(provide 'brz)

