"""Built-in skills loaded into memory on first start (kind=skill, source=seed)."""

SEED_SKILLS = [
    (
        "Run a Python script on Kaggle",
        "Any task that needs compute on Kaggle (training, conversion, downloading a model, data work)",
        """1. Write ONE self-contained script. Save every output file into /kaggle/working.
2. kaggle_push_run(slug, code). Use CPU unless the task truly needs a GPU (GPU needs owner approval).
3. wait_for(what='kaggle_kernel', ref=slug). Do not poll in a loop.
4. When woken: kaggle_status. If complete -> kaggle_output and check files + log tail. If error -> read the log tail, fix the script, push again.
5. internet=true is needed for downloading from Hugging Face/pip inside the script.""",
    ),
    (
        "Host an open model on a Hugging Face Space",
        "Owner wants a model served behind an API",
        """Path A (model already on the Hub): hf_deploy_space(space_name, model_id, task) -> wait_for(hf_space) -> hf_space_predict to verify -> finish_task with the Space URL.
Path B (model produced on Kaggle): kaggle_output -> hf_upload_model(repo_name, kernel_slug) -> hf_deploy_space with the new model_id (needs_token=true if the model repo is private, needs approval) -> wait_for -> hf_space_predict.
Keep Spaces private unless the owner asks otherwise. Free CPU Spaces suit small models only: if the build or load fails for memory reasons, say so and propose a smaller model.
Always finish with: URL, how to call it (api_name '/predict', inputs [text, max_new_tokens]), and whether it is private.""",
    ),
    (
        "Debug a failed Kaggle run",
        "kaggle_status says error or the log shows a traceback",
        """1. kaggle_output and read log_tail from the bottom: the last traceback line is the cause.
2. Typical causes: missing pip package (add a pip install at the top of the script), no internet (push with internet=true), out of memory (smaller model / batch), wrong path (write to /kaggle/working).
3. Change one thing, push again, wait_for. Never repeat an identical failing push.
4. After fixing, save_lesson with the exact error text as evidence.""",
    ),
]
