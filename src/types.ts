export interface GoogleKeepListItem {
  checked?: boolean;
  childListItems?: GoogleKeepListItem[];
  text?: {
    text?: string;
  };
}

export interface GoogleKeepNote {
  body?: {
    list?: {
      listItems?: GoogleKeepListItem[];
    };
    text?: {
      text?: string;
    };
  };
  createTime?: string;
  name?: string;
  title?: string;
  trashed?: boolean;
  updateTime?: string;
}

export interface GoogleKeepListResponse {
  nextPageToken?: string;
  notes?: GoogleKeepNote[];
}

export interface KeepNote {
  createdAt?: string;
  isList: boolean;
  name: string;
  text: string;
  title: string;
  updatedAt?: string;
}

export interface WorkspaceKeepPreferences {
  googleClientId: string;
}
